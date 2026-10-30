// Minimal typings for the positioning forces used by the network graph (d3-force-3d ships no types).
declare module 'd3-force-3d' {
  type PositionForce = ((alpha: number) => void) & { strength(value: number): PositionForce };
  export function forceX(x?: number): PositionForce;
  export function forceY(y?: number): PositionForce;
  export function forceZ(z?: number): PositionForce;
}
