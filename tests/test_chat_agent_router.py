from api.routers.chat_agents import ChatAgentRouteRequest, _fallback_route


def test_save_note_fallback_ignores_generic_notebook_mentions():
    response = _fallback_route(
        ChatAgentRouteRequest(
            surface="global_chat",
            message="Resume este notebook em três pontos.",
        ),
        "router disabled",
    )

    assert response.agent != "save_note"


def test_save_note_fallback_routes_explicit_save_note_request():
    response = _fallback_route(
        ChatAgentRouteRequest(
            surface="global_chat",
            message="Guarda isto como nota no meu notebook.",
        ),
        "router disabled",
    )

    assert response.agent == "save_note"
