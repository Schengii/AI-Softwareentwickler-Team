// Sicheres Upload-Handling
const ALLOWED_TYPES = ['text/csv', 'application/json'];
const ALLOWED_EXTENSIONS = ['.csv', '.json'];
const MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024; // 5MB

export const validateUploadedFile = (file) => {
  if (!file) return { valid: false, error: 'Keine Datei ausgewählt.' };
  if (file.size > MAX_FILE_SIZE_BYTES) return { valid: false, error: 'Datei überschreitet 5MB Limits.' };
  
  const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(ext)) return { valid: false, error: 'Ungültiges Dateiformat. Nur CSV/JSON erlaubt.' };
  
  return { valid: true, error: null };
};
