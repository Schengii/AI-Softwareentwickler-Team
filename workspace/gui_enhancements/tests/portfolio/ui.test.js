import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { AnimatedCard } from '../../src/components/AnimatedCard';
import { Modal } from '../../src/components/Modal';

describe('UI Components Unit Tests', () => {
  describe('AnimatedCard', () => {
    test('renders correctly with props', () => {
      const mockOnClick = jest.fn();
      render(<AnimatedCard title="Test Card" description="Test Desc" onClick={mockOnClick} />);
      
      expect(screen.getByText('Test Card')).toBeInTheDocument();
      expect(screen.getByText('Test Desc')).toBeInTheDocument();
      
      fireEvent.click(screen.getByText('Test Card'));
      expect(mockOnClick).toHaveBeenCalled();
    });
  });

  describe('Modal', () => {
    test('renders when open', () => {
      const mockOnClose = jest.fn();
      render(
        <Modal isOpen={true} onClose={mockOnClose} title="Test Modal">
          <p>Modal Content</p>
        </Modal>
      );
      
      expect(screen.getByText('Test Modal')).toBeInTheDocument();
      expect(screen.getByText('Modal Content')).toBeInTheDocument();
      
      fireEvent.click(screen.getByText('Schließen'));
      expect(mockOnClose).toHaveBeenCalled();
    });

    test('does not render when closed', () => {
      render(
        <Modal isOpen={false} onClose={() => {}}>
          <p>Hidden Content</p>
        </Modal>
      );
      expect(screen.queryByText('Hidden Content')).not.toBeInTheDocument();
    });
  });
});
