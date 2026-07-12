import type { CompareCombination } from "./matrix";

const UINT32_SIZE = 0x1_0000_0000;

export type CompareRunItem = {
  runId: string;
  groupIndex: number;
  groupSeed: number;
  combination: CompareCombination;
};

export type CompareGroupPlan = {
  groupIndex: number;
  seed: number;
  items: CompareRunItem[];
};

export type CompareRunPlan = {
  groups: CompareGroupPlan[];
  items: CompareRunItem[];
};

function normalizeSeed(value: number): number {
  const integer = Number.isFinite(value) ? Math.trunc(value) : 0;
  return ((integer % UINT32_SIZE) + UINT32_SIZE) % UINT32_SIZE;
}

function distinctSeed(candidate: number, used: Set<number>): number {
  let seed = normalizeSeed(candidate);
  while (used.has(seed)) seed = normalizeSeed(seed + 1);
  used.add(seed);
  return seed;
}

export function buildCompareRunPlan(
  matrix: CompareCombination[],
  options: { nt: number; seed: string; randomSeed(): number },
): CompareRunPlan {
  if (!Number.isSafeInteger(options.nt) || options.nt < 1) {
    throw new Error("Compare NT 必须是大于等于 1 的整数");
  }

  const parsedSeed = Number(options.seed);
  const explicitSeed = Number.isInteger(parsedSeed) && parsedSeed >= 0;
  const usedSeeds = new Set<number>();
  const groups = Array.from({ length: options.nt }, (_, offset) => {
    const groupIndex = offset + 1;
    const seed = distinctSeed(
      explicitSeed ? parsedSeed + offset : options.randomSeed(),
      usedSeeds,
    );
    const prefix = `group-${String(groupIndex).padStart(3, "0")}`;
    const items = matrix.map((combination) => ({
      runId: `${prefix}::${combination.combinationId}`,
      groupIndex,
      groupSeed: seed,
      combination,
    }));
    return { groupIndex, seed, items };
  });

  return { groups, items: groups.flatMap((group) => group.items) };
}

export function compareRunCount(matrixCount: number, nt: number): number {
  return Number.isSafeInteger(nt) && nt >= 1 ? matrixCount * nt : 0;
}
