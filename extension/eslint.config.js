export default [
  {
    ignores: ["dist/**", "node_modules/**", "web-ext-artifacts/**", "tests/fixtures/**", "tests/e2e/.venv/**", "tests/e2e/.tools/**"],
  },
  {
    files: ["**/*.js", "**/*.mjs"],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "module",
      globals: {
        globalThis: "readonly",
        console: "readonly",
        document: "readonly",
        window: "readonly",
        navigator: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        requestAnimationFrame: "readonly",
      },
    },
    rules: {
      "no-unused-vars": ["error", { args: "none", caughtErrors: "none" }],
      "no-restricted-syntax": [
        "error",
        {
          selector: "MemberExpression[object.name='browser']",
          message: "use src/shared/api.js; the extension API has one module",
        },
        {
          selector: "MemberExpression[object.name='chrome']",
          message: "use src/shared/api.js; the extension API has one module",
        },
        {
          selector: "MemberExpression[property.name='innerHTML']",
          message: "build DOM with textContent only",
        },
        {
          selector: "MemberExpression[property.name='outerHTML']",
          message: "build DOM with textContent only",
        },
        {
          selector: "MemberExpression[property.name='insertAdjacentHTML']",
          message: "build DOM with textContent only",
        },
      ],
    },
  },
  {
    files: ["src/shared/api.js"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "MemberExpression[property.name='innerHTML']",
          message: "build DOM with textContent only",
        },
        {
          selector: "MemberExpression[property.name='outerHTML']",
          message: "build DOM with textContent only",
        },
        {
          selector: "MemberExpression[property.name='insertAdjacentHTML']",
          message: "build DOM with textContent only",
        },
      ],
    },
  },
  {
    files: ["src/background/**/*.js"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "MemberExpression[object.name='browser']",
          message: "use src/shared/api.js; the extension API has one module",
        },
        {
          selector: "MemberExpression[object.name='chrome']",
          message: "use src/shared/api.js; the extension API has one module",
        },
        {
          selector: "MemberExpression[property.name='innerHTML']",
          message: "build DOM with textContent only",
        },
        {
          selector: "MemberExpression[property.name='outerHTML']",
          message: "build DOM with textContent only",
        },
        {
          selector: "MemberExpression[property.name='insertAdjacentHTML']",
          message: "build DOM with textContent only",
        },
        {
          selector: "Identifier[name='window']",
          message: "the background is a service worker: no window",
        },
        {
          selector: "Identifier[name='document']",
          message: "the background is a service worker: no document",
        },
      ],
    },
  },
  {
    files: ["tests/**/*.js", "build.mjs"],
    languageOptions: {
      globals: {
        console: "readonly",
        process: "readonly",
        Buffer: "readonly",
      },
    },
  },
];