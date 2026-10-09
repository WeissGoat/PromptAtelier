import { describe, expect, it } from "vitest";

import fixtures from "../../../tests/fixtures/prompt_tokens.json";
import { innerTags, serialize, tokenize } from "./tokens";

describe("prompt tokenizer (shared fixtures with backend)", () => {
  for (const testCase of fixtures.tokenize) {
    it(`tokenizes: ${testCase.name}`, () => {
      const result = tokenize(testCase.input);
      expect(result.tokens.map((token) => token.text)).toEqual(testCase.tokens);
      expect(serialize(result)).toBe(testCase.input);
    });
  }

  for (const testCase of fixtures.inner_tags) {
    it(`inner tags: ${testCase.input}`, () => {
      expect(innerTags(testCase.input)).toEqual(testCase.tags);
    });
  }

  for (const testCase of fixtures.serialize) {
    it(`serializes: ${testCase.name}`, () => {
      expect(serialize({ leading: testCase.leading, tokens: testCase.tokens, trailing: testCase.trailing })).toBe(
        testCase.output,
      );
    });
  }
});
