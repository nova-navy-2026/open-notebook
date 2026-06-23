"use client";

import { type ComponentType, type Ref } from "react";
import ForceGraph2D from "react-force-graph-2d";

// Thin client-only wrapper so an imperative ref survives `next/dynamic`
// (which does not forward refs). We pass the ref through a plain `innerRef`
// prop instead. react-force-graph-2d touches `window`, so this module must
// only ever be loaded via dynamic import with `ssr: false`.
interface WrapperProps {
  innerRef?: Ref<unknown>;
  [key: string]: unknown;
}

export default function ForceGraphClient({ innerRef, ...props }: WrapperProps) {
  const Component = ForceGraph2D as unknown as ComponentType<
    Record<string, unknown> & { ref?: Ref<unknown> }
  >;
  return <Component ref={innerRef} {...props} />;
}
