/* eslint-env node */
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended-type-checked",
    "plugin:react-hooks/recommended",
    "prettier",
  ],
  parser: "@typescript-eslint/parser",
  parserOptions: {
    project: ["./tsconfig.app.json"],
    tsconfigRootDir: __dirname,
  },
  plugins: ["@typescript-eslint", "react-refresh"],
  ignorePatterns: [
    "dist",
    "node_modules",
    ".eslintrc.cjs",
    "*.config.ts",
    "*.config.js",
    "vitest.setup.ts",
    "src/e2e/**",
  ],
  rules: {
    "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    "@typescript-eslint/consistent-type-imports": "error",
  },
  overrides: [
    {
      files: ["**/*.test.{ts,tsx}"],
      rules: {
        "@typescript-eslint/no-unsafe-assignment": "off",
        "@typescript-eslint/no-unsafe-member-access": "off",
        "@typescript-eslint/no-unsafe-call": "off",
        "@typescript-eslint/unbound-method": "off",
      },
    },
    {
      // Barrels, route/config modules, and test helpers legitimately export non-components.
      files: ["src/**/index.ts", "src/app/router.tsx", "src/**/*TestUtils.tsx"],
      rules: { "react-refresh/only-export-components": "off" },
    },
  ],
};
