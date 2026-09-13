// ui-src/main.ts
import { html, render } from 'lit';
import './components/onboarding-screen';
import './components/reading-ruler';

const appTemplate = html`
  <onboarding-screen></onboarding-screen>
  <reading-ruler></reading-ruler>
`;

const appRoot = document.getElementById('app');
if (appRoot) {
  render(appTemplate, appRoot);
} else {
  console.error('Kritischer Fehler: App-Root-Element (#app) nicht in index.html gefunden.');
}
