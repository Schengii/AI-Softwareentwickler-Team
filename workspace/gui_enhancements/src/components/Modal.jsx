import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';

export const Modal = ({ isOpen, onClose, title, children }) => (
  <AnimatePresence>
    {isOpen && (
      <>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 0.5 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black"
          onClick={onClose}
        />
        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 p-6 bg-background-light dark:bg-background-dark rounded-lg shadow-xl z-50"
        >
          {title && <h2 className="text-2xl mb-4">{title}</h2>}
          {children}
          <button onClick={onClose} className="mt-4 px-4 py-2 bg-primary-light text-white rounded">Schließen</button>
        </motion.div>
      </>
    )}
  </AnimatePresence>
);
