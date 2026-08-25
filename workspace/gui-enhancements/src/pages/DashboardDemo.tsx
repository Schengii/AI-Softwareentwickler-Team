import { motion } from 'framer-motion';
import { AnimatedBox } from '../components/AnimatedBox';
import { ANIMATION_VARIANTS } from '../styles/designTokens';

const KACHELN = [
  "Depotwert", "Performance", "Asset-Verteilung",
  "Top Performer", "Transaktionen", "Dividenden",
  "Risiko-Analyse", "Markt-News", "Einstellungen"
];

export const DashboardDemo = () => (
  <motion.div
    variants={ANIMATION_VARIANTS.staggerContainer}
    initial="hidden"
    animate="visible"
    className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 p-6"
  >
    {KACHELN.map((titel) => (
      <AnimatedBox key={titel} className="p-6 bg-white shadow-md rounded-xl border border-gray-200">
        <h2 className="text-lg font-semibold text-gray-800">{titel}</h2>
      </AnimatedBox>
    ))}
  </motion.div>
);
