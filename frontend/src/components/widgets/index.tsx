"use client";

import { AttentionMatrix } from "./attention-matrix";
import { DerivativeTangent } from "./derivative-tangent";
import { GradientDescent2D } from "./gradient-descent-2d";
import { MatrixTransform2D } from "./matrix-transform";
import { VectorDotProduct } from "./vector-dot-product";

/** Fixed widget registry — lessons (including AI-generated ones) can only reference these names. */
const REGISTRY: Record<string, React.ComponentType<{ params: Record<string, number> }>> = {
  vector_dot_product: VectorDotProduct,
  matrix_transform_2d: MatrixTransform2D,
  derivative_tangent: DerivativeTangent,
  gradient_descent_2d: GradientDescent2D,
  attention_matrix: AttentionMatrix,
};

export function Widget({ name, params }: { name: string; params: { name: string; value: number }[] }) {
  const C = REGISTRY[name];
  if (!C) return <p className="text-sm text-muted-foreground">Unknown interactive widget “{name}”.</p>;
  return <C params={Object.fromEntries(params.map((p) => [p.name, p.value]))} />;
}
