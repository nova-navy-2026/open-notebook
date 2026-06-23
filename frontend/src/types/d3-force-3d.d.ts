// Minimal type surface for `d3-force-3d`, the simulation engine bundled by
// react-force-graph-2d. The package ships no types; we declare only the forces
// we use (a collision force to stop node overlap, plus positional X/Y forces to
// anchor each topic cluster in its own region). Importing from this exact
// package keeps the node objects compatible with the graph's own simulation.
declare module "d3-force-3d" {
  interface Collide<N> {
    radius(r: number | ((n: N) => number)): Collide<N>;
    strength(s: number): Collide<N>;
    iterations(n: number): Collide<N>;
  }
  export function forceCollide<N = unknown>(
    radius?: number | ((n: N) => number),
  ): Collide<N>;

  interface Positional<N> {
    x?(x: number | ((n: N) => number)): Positional<N>;
    y?(y: number | ((n: N) => number)): Positional<N>;
    strength(s: number | ((n: N) => number)): Positional<N>;
  }
  export function forceX<N = unknown>(
    x?: number | ((n: N) => number),
  ): Positional<N>;
  export function forceY<N = unknown>(
    y?: number | ((n: N) => number),
  ): Positional<N>;
}
