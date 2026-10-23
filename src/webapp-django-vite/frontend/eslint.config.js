import js from "@eslint/js";

export default [
  {
    ignores: ["dist/**"],
  },
  js.configs.recommended,
  {
    files: ["src/**/*.js", "vite.config.js"],
    languageOptions: {
      globals: {
        console: "readonly",
        document: "readonly",
        fetch: "readonly",
        FormData: "readonly",
        Headers: "readonly",
        setInterval: "readonly",
        URLSearchParams: "readonly",
        window: "readonly",
      },
    },
  },
];
