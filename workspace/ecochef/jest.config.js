  module.exports = {
    preset: 'ts-jest',
    testEnvironment: 'jsdom',
    roots: ['<rootDir>/ui-src', '<rootDir>/tests'],
    moduleFileExtensions: ['ts', 'js', 'json'],
    transform: { '^.+\\.ts$': 'ts-jest' }
  };
  