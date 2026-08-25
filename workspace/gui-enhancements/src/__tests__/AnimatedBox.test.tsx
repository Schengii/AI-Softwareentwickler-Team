import { render, screen } from '@testing-library/react';
import React from 'react';
import AnimatedBox from '../src/components/AnimatedBox';

describe('AnimatedBox Component', () => {
  test('renders without crashing', () => {
    render(<AnimatedBox />);
    // Hier könnte man spezifischere Selektoren hinzufügen, 
    // wenn das Component-Interface bekannt ist.
  });
});
