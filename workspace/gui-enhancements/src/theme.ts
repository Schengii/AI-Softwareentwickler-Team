import { createContext } from 'react';
import { COLORS } from './styles/designTokens';

export type ThemeMode = 'light' | 'dark';

export interface Theme {
  primary: string;
  background: string;
  contrastText: string;
  surface: string;
  mode: ThemeMode;
}

export const getTheme = (mode: ThemeMode): Theme => ({
  ...COLORS[mode],
  mode,
});

export const ThemeContext = createContext<Theme>(getTheme('light'));
