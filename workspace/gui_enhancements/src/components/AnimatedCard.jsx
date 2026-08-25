import React from 'react';
import { motion } from 'framer-motion';

export const AnimatedCard = ({ title, description, onClick }) => (
  <motion.div
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    whileHover={{ scale: 1.02 }}
    className="p-6 bg-surface-light dark:bg-surface-dark rounded-xl shadow-md cursor-pointer"
    onClick={onClick}
  >
    <h3 className="text-xl font-bold text-text-light dark:text-text-dark">{title}</h3>
    <p className="mt-2 text-text-light/80 dark:text-text-dark/80">{description}</p>
  </motion.div>
);
