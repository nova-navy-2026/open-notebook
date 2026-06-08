"""
Chart generation API router — the backend for the ``graph_generator`` chat
agent.

The agent receives a tabular file (CSV/TSV/JSON/Excel) or inline CSV data plus
a natural-language instruction ("plot sales per month as a bar chart") and
returns a rendered chart image (PNG, base64 data URL) that the frontend shows
inline and lets the user download.

Security model
--------------
No user-supplied code is ever executed. The LLM is only asked to produce a
*constrained* chart specification (chart type + which columns to use); the
chart itself is rendered deterministically with matplotlib. The spec is
validated against the real columns before rendering, and the input size /
row count are capped to avoid resource-exhaustion. When no model is
available (or the model misbehaves) a deterministic heuristic spec is used,
so the agent still works without an LLM.
"""

import base64
import io
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel, Field

from api.auth import get_current_user_id
from api.chat_agent_log_service import build_chat_agent_event, write_chat_agent_event

router = APIRouter()

# Hard limits to keep parsing/rendering bounded.
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
MAX_ROWS = 100_000  # rows considered for aggregation/plotting
MAX_SERIES = 6  # max number of y-series plotted at once
MAX_PIE_SLICES = 20

ALLOWED_EXTENSIONS = {".csv", ".tsv", ".txt", ".json", ".xlsx", ".xls"}
CHART_TYPES = {"bar", "line", "scatter", "pie", "hist", "box", "area"}
AGGREGATIONS = {"none", "sum", "mean", "median", "count", "min", "max"}


class ChartSpec(BaseModel):
    """Constrained chart specification produced by the LLM (or heuristic)."""

    chart_type: str = Field(description="One of: bar, line, scatter, pie, hist, box, area")
    x: Optional[str] = Field(default=None, description="Column for the x axis / category / labels")
    y: List[str] = Field(default_factory=list, description="One or more numeric columns to plot")
    aggregation: str = Field(default="none", description="none, sum, mean, median, count, min, max")
    title: str = Field(default="", description="Chart title")
    x_label: str = Field(default="", description="X axis label")
    y_label: str = Field(default="", description="Y axis label")


class ChartResponse(BaseModel):
    text: str
    image_base64: Optional[str] = None
    spec: Optional[Dict[str, Any]] = None
    table_preview: Optional[str] = None


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _read_table(filename: Optional[str], content: bytes, inline_data: Optional[str]):
    """Parse uploaded bytes (or inline CSV text) into a pandas DataFrame."""
    import pandas as pd

    if content:
        ext = Path(filename or "").suffix.lower()
        bio = io.BytesIO(content)
        try:
            if ext == ".tsv":
                return pd.read_csv(bio, sep="\t")
            if ext == ".json":
                return pd.read_json(bio)
            if ext in {".xlsx", ".xls"}:
                return pd.read_excel(bio)
            # .csv / .txt / unknown → try comma-separated, then auto-sniff.
            return pd.read_csv(bio)
        except Exception:
            bio.seek(0)
            return pd.read_csv(bio, sep=None, engine="python")

    if inline_data and inline_data.strip():
        return pd.read_csv(io.StringIO(inline_data))

    raise ValueError("No tabular data provided.")


def _column_metadata(df) -> List[Dict[str, str]]:
    meta: List[Dict[str, str]] = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        sample = ", ".join(str(v) for v in df[col].dropna().head(3).tolist())
        meta.append({"name": str(col), "dtype": dtype, "sample": sample})
    return meta


# ---------------------------------------------------------------------------
# Spec generation (LLM with heuristic fallback)
# ---------------------------------------------------------------------------

async def _llm_chart_spec(
    query: str, df, model_id: Optional[str]
) -> Optional[ChartSpec]:
    """Ask the configured model for a constrained ChartSpec. Never raises."""
    try:
        from langchain_core.output_parsers.pydantic import PydanticOutputParser

        from open_notebook.ai.provision import provision_langchain_model

        parser = PydanticOutputParser(pydantic_object=ChartSpec)
        columns = _column_metadata(df)
        prompt = (
            "You translate a user's natural-language charting request into a "
            "strict JSON chart specification. Use ONLY the column names listed.\n\n"
            f"User request: {query}\n\n"
            f"Available columns (name, dtype, sample):\n"
            + "\n".join(f"- {c['name']} ({c['dtype']}): {c['sample']}" for c in columns)
            + "\n\nRules:\n"
            "- chart_type must be one of: bar, line, scatter, pie, hist, box, area.\n"
            "- y must be numeric columns. x is the category/time/label column.\n"
            "- For pie: x = labels column, y = a single numeric column.\n"
            "- For hist/box: y = numeric column(s); x may be empty.\n"
            "- aggregation is one of none, sum, mean, median, count, min, max.\n\n"
            f"{parser.get_format_instructions()}\n"
            "Return ONLY the JSON object."
        )
        model = await provision_langchain_model(
            prompt, model_id, "tools", max_tokens=500, structured=dict(type="json")
        )
        ai_message = await model.ainvoke(prompt)
        content = ai_message.content
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        return parser.parse(str(content))
    except Exception as e:
        logger.warning(f"Chart spec LLM generation failed, using heuristic: {e}")
        return None


def _heuristic_chart_spec(query: str, df) -> ChartSpec:
    """Deterministic fallback spec derived from the data + a few keywords."""
    import pandas as pd

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    non_numeric = [c for c in df.columns if c not in numeric_cols]
    q = (query or "").lower()

    if any(w in q for w in ("histogram", "histograma", "distribuição", "distribuicao")):
        return ChartSpec(chart_type="hist", y=numeric_cols[:1] or list(df.columns[:1]))
    if any(w in q for w in ("scatter", "dispersão", "dispersao", "correlação", "correlacao")) and len(numeric_cols) >= 2:
        return ChartSpec(chart_type="scatter", x=numeric_cols[0], y=[numeric_cols[1]])
    if any(w in q for w in ("pie", "pizza", "circular", "proporção", "proporcao")) and non_numeric and numeric_cols:
        return ChartSpec(chart_type="pie", x=non_numeric[0], y=[numeric_cols[0]])
    if any(w in q for w in ("line", "linha", "tendência", "tendencia", "ao longo", "tempo", "evolução", "evolucao")):
        chart_type = "line"
    else:
        chart_type = "bar"

    x = non_numeric[0] if non_numeric else (df.columns[0] if len(df.columns) else None)
    y = [c for c in numeric_cols if c != x][:MAX_SERIES] or numeric_cols[:MAX_SERIES]
    return ChartSpec(chart_type=chart_type, x=x, y=y)


def _validate_spec(spec: ChartSpec, df) -> ChartSpec:
    """Coerce an LLM/heuristic spec to something renderable against this data."""
    import pandas as pd

    cols = list(df.columns)
    numeric_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]

    chart_type = spec.chart_type if spec.chart_type in CHART_TYPES else "bar"
    aggregation = spec.aggregation if spec.aggregation in AGGREGATIONS else "none"

    x = spec.x if spec.x in cols else None
    y = [c for c in spec.y if c in cols][:MAX_SERIES]

    # Ensure y are numeric for the chart types that require it.
    if chart_type in {"bar", "line", "area", "scatter", "pie", "box", "hist"}:
        y_numeric = [c for c in y if c in numeric_cols]
        if not y_numeric:
            y_numeric = numeric_cols[:1] if chart_type in {"hist", "box"} else numeric_cols[:MAX_SERIES]
        y = y_numeric

    if chart_type not in {"hist", "box"} and x is None:
        non_numeric = [c for c in cols if c not in numeric_cols]
        x = non_numeric[0] if non_numeric else (cols[0] if cols else None)

    if not y:
        raise HTTPException(
            status_code=422,
            detail="Could not find any numeric column to plot in the provided data.",
        )

    return ChartSpec(
        chart_type=chart_type,
        x=x,
        y=y,
        aggregation=aggregation,
        title=spec.title,
        x_label=spec.x_label,
        y_label=spec.y_label,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _aggregate(df, spec: ChartSpec):
    """Apply the requested aggregation, grouping by the x column when set."""
    if spec.aggregation == "none" or not spec.x or spec.chart_type in {"hist", "box", "scatter"}:
        return df
    func = "size" if spec.aggregation == "count" else spec.aggregation
    grouped = df.groupby(spec.x)[spec.y]
    agg = grouped.agg(func)
    return agg.reset_index()


def _render_chart(df, spec: ChartSpec) -> bytes:
    """Render the chart to PNG bytes using a non-interactive matplotlib backend."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:  # optional nicer styling
        import seaborn as sns  # type: ignore

        sns.set_theme(style="whitegrid")
    except Exception:
        plt.style.use("default")

    data = _aggregate(df, spec)
    fig, ax = plt.subplots(figsize=(9, 5))

    try:
        if spec.chart_type == "hist":
            for col in spec.y:
                ax.hist(data[col].dropna(), bins=30, alpha=0.6, label=str(col))
            if len(spec.y) > 1:
                ax.legend()
        elif spec.chart_type == "box":
            ax.boxplot([data[col].dropna() for col in spec.y], labels=[str(c) for c in spec.y])
        elif spec.chart_type == "scatter":
            ax.scatter(data[spec.x], data[spec.y[0]], alpha=0.7)
        elif spec.chart_type == "pie":
            sliced = data.head(MAX_PIE_SLICES)
            ax.pie(sliced[spec.y[0]], labels=[str(v) for v in sliced[spec.x]], autopct="%1.1f%%")
            ax.axis("equal")
        elif spec.chart_type in {"line", "area"}:
            for col in spec.y:
                if spec.chart_type == "area":
                    ax.fill_between(range(len(data)), data[col], alpha=0.4, label=str(col))
                else:
                    ax.plot(data[spec.x] if spec.x else range(len(data)), data[col], marker="o", label=str(col))
            if spec.x and spec.chart_type == "area":
                ax.set_xticks(range(len(data)))
                ax.set_xticklabels([str(v) for v in data[spec.x]], rotation=45, ha="right")
            ax.legend()
        else:  # bar (default)
            import numpy as np

            x_vals = data[spec.x] if spec.x else range(len(data))
            positions = np.arange(len(data))
            width = 0.8 / max(1, len(spec.y))
            for i, col in enumerate(spec.y):
                ax.bar(positions + i * width, data[col], width=width, label=str(col))
            ax.set_xticks(positions + width * (len(spec.y) - 1) / 2)
            ax.set_xticklabels([str(v) for v in x_vals], rotation=45, ha="right")
            if len(spec.y) > 1:
                ax.legend()

        ax.set_title(spec.title or "")
        if spec.chart_type not in {"pie"}:
            ax.set_xlabel(spec.x_label or (str(spec.x) if spec.x else ""))
            ax.set_ylabel(spec.y_label or (", ".join(str(c) for c in spec.y)))

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        return buf.getvalue()
    finally:
        plt.close(fig)


def _summary_text(df, spec: ChartSpec) -> str:
    rows = len(df)
    cols = ", ".join(str(c) for c in spec.y)
    by = f" agrupado por **{spec.x}**" if spec.x and spec.aggregation != "none" else ""
    agg = "" if spec.aggregation == "none" else f" ({spec.aggregation})"
    return (
        f"Gráfico de **{spec.chart_type}** gerado a partir de {rows} linhas. "
        f"Séries: **{cols}**{agg}{by}."
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/charts/generate", response_model=ChartResponse)
async def generate_chart(
    query: str = Form(...),
    data: Optional[str] = Form(None),
    model_id: Optional[str] = Form(None),
    surface: str = Form("global_chat"),
    run_id: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    notebook_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    user_id: str = Depends(get_current_user_id),
):
    """Generate a chart from an uploaded table (or inline CSV) + an instruction.

    Returns the chart as a base64 PNG data URL plus a short summary and a
    small markdown preview of the data.
    """
    started_at = perf_counter()

    content = b""
    if file and file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported file type '{ext}'. Allowed: "
                    f"{', '.join(sorted(ALLOWED_EXTENSIONS))}"
                ),
            )
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {MAX_FILE_SIZE // (1024 * 1024)} MB limit.",
            )

    if not content and not (data and data.strip()):
        raise HTTPException(
            status_code=400,
            detail="Provide a tabular file (CSV/TSV/JSON/Excel) or inline CSV data.",
        )

    try:
        import pandas  # noqa: F401
    except Exception:
        raise HTTPException(
            status_code=501,
            detail="Charting dependencies (pandas/matplotlib) are not installed on the server.",
        )

    try:
        df = _read_table(file.filename if file else None, content, data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse the data: {e}")

    if df is None or df.empty:
        raise HTTPException(status_code=422, detail="The provided data is empty.")

    if len(df) > MAX_ROWS:
        df = df.head(MAX_ROWS)

    spec = await _llm_chart_spec(query, df, model_id) or _heuristic_chart_spec(query, df)
    spec = _validate_spec(spec, df)

    try:
        png = _render_chart(df, spec)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chart rendering failed: {e}")
        raise HTTPException(status_code=500, detail=f"Chart rendering failed: {e}")

    image_b64 = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    table_preview = None
    try:
        table_preview = df.head(10).to_markdown(index=False)
    except Exception:
        pass

    duration_ms = int((perf_counter() - started_at) * 1000)
    try:
        await write_chat_agent_event(
            build_chat_agent_event(
                source="backend",
                user_id=user_id,
                surface=surface or "global_chat",
                run_id=run_id,
                session_id=session_id,
                notebook_id=notebook_id,
                model_id=model_id,
                agent="graph_generator",
                event="tool_call",
                status="success",
                file={
                    "name": file.filename if file else None,
                    "type": file.content_type if file else "text/csv",
                    "size": len(content) if content else None,
                },
                duration_ms=duration_ms,
                details={"chart_type": spec.chart_type, "rows": len(df)},
            )
        )
    except Exception:
        pass

    return ChartResponse(
        text=_summary_text(df, spec),
        image_base64=image_b64,
        spec=json.loads(spec.model_dump_json()),
        table_preview=table_preview,
    )
