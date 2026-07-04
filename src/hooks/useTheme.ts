import { useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "faces_h_theme";

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", theme);
  }
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(() => {
    return (localStorage.getItem(STORAGE_KEY) as Theme | null) ?? "system";
  });

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  function setTheme(t: Theme) {
    localStorage.setItem(STORAGE_KEY, t);
    setThemeState(t);
    applyTheme(t);
  }

  return [theme, setTheme];
}
