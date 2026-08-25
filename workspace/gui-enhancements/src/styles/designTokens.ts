export const ANIMATION_VARIANTS = {
  fadeInUp: {
    hidden: { opacity: 0, y: 20 },
    visible: { 
      opacity: 1, 
      y: 0,
      transition: { duration: 0.3, ease: [0.4, 0, 0.2, 1] }
    }
  },
  staggerContainer: {
    visible: {
      transition: { staggerChildren: 0.05 }
    }
  }
};

export const COLORS = {
  light: {
    primary: "#2563EB",
    background: "#F8FAFC",
    contrastText: "#0F172A",
    surface: "#FFFFFF"
  },
  dark: {
    primary: "#3B82F6",
    background: "#0F172A",
    contrastText: "#F8FAFC",
    surface: "#1E293B"
  }
};
