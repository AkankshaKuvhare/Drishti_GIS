/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#12151A",
        panel: "#181C23",
        accent: "#3ED0C4",
        confhigh: "#33C481",
        confmid: "#E8B93E",
        conflow: "#E2593C",
      },
    },
  },
  plugins: [],
};
