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

function distinctSeedBlock(candidate: number, blockSize: number, used: Set<number>): number {
  let seed = normalizeSeed(candidate);
  const conflicts = (s: number) => {
    for (let i = 0; i < blockSize; i += 1) {
      if (used.has(normalizeSeed(s + i))) return true;
    }
    return false;
  };
  while (conflicts(seed)) {
    seed = normalizeSeed(seed + blockSize);
  }
  for (let i = 0; i < blockSize; i += 1) {
    used.add(normalizeSeed(seed + i));
  }
  return seed;
}

export function buildCompareRunPlan(
  matrix: CompareCombination[],
  options: { n: number; nt?: number; seed: string; randomSeed(): number },
): CompareRunPlan {
  if (!Number.isSafeInteger(options.n) || options.n < 1) {
    throw new Error("Compare N 必须是大于等于 1 的整数");
  }

  const nt = Math.max(1, Math.trunc(options.nt ?? 1));
  const parsedSeed = Number(options.seed);
  const explicitSeed = Number.isInteger(parsedSeed) && parsedSeed >= 0;
  const usedSeeds = new Set<number>();
  const groups = Array.from({ length: options.n }, (_, offset) => {
    const groupIndex = offset + 1;
    const seed = distinctSeedBlock(
      explicitSeed ? parsedSeed + offset * nt : options.randomSeed(),
      nt,
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

export function compareRunCount(matrixCount: number, n: number, nt: number = 1): number {
  const safeN = Number.isSafeInteger(n) && n >= 1 ? n : 0;
  const safeNt = Number.isSafeInteger(nt) && nt >= 1 ? nt : 0;
  return matrixCount * safeN * safeNt;
}
