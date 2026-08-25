import { motion } from 'framer-motion';
import { ReactNode } from 'react';
import { ANIMATION_VARIANTS } from '../styles/designTokens';

interface Props {
  children: ReactNode;
  className?: string;
}

export const AnimatedBox = ({ children, className }: Props) => (
  <motion.div
    variants={ANIMATION_VARIANTS.fadeInUp}
    initial="hidden"
    animate="visible"
    className={className}
  >
    {children}
  </motion.div>
);
