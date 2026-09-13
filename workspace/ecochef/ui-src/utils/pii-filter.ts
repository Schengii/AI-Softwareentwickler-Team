/**
 * PII-Maskierungsfilter zur DSGVO-konformen Vorab-Bereinigung von Prompts
 * Maskiert Namen, E-Mail-Adressen, Telefonnummern und postalische Adressen.
 */
export class PiiFilter {
  private static readonly EMAIL_REGEX = /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/gi;
  private static readonly PHONE_REGEX = /(?:\+?\d{1,3}[\s-]?)?\(?\d{2,5}\)?[\s-]?\d{3,}[\s-]?\d{3,}/g;
  private static readonly POSTAL_CODE_REGEX = /\b\d{5}\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)*)\b/g;
  private static readonly STREET_REGEX = /\b([A-ZÄÖÜ][a-zäöüß]+(?:straße|str\.|weg|gasse|platz|allee|damm))\s+\d+[a-zA-Z]?\b/gi;
  private static readonly NAME_PATTERNS = [
    /(?:ich heiße|mein name ist|ich bin|name:\s*)\s*([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)/gi,
    /(?:für|von)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)\b/gi
  ];

  /**
   * Filtert und maskiert potenziell personenbezogene Daten aus Freitextfeldern.
   */
  public static maskPii(text: string): string {
    if (!text) return '';

    let sanitized = text;

    // E-Mail-Adressen
    sanitized = sanitized.replace(this.EMAIL_REGEX, '[REDACTED_EMAIL]');

    // Telefonnummern
    sanitized = sanitized.replace(this.PHONE_REGEX, '[REDACTED_PHONE]');

    // Straßen und Hausnummern
    sanitized = sanitized.replace(this.STREET_REGEX, '[REDACTED_ADDRESS]');

    // Postleitzahl + Ort
    sanitized = sanitized.replace(this.POSTAL_CODE_REGEX, '[REDACTED_LOCATION]');

    // Namen nach typischen Mustern
    for (const pattern of this.NAME_PATTERNS) {
      sanitized = sanitized.replace(pattern, (match, p1) => {
        return match.replace(p1, '[REDACTED_NAME]');
      });
    }

    return sanitized;
  }
}
