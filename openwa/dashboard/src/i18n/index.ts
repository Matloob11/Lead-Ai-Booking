import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';
import de from './locales/de.json';
import es from './locales/es.json';
import he from './locales/he.json';
import zhCN from './locales/zh-CN.json';
import zhHK from './locales/zh-HK.json';
import ar from './locales/ar.json';
import te from './locales/te.json';
import fr from './locales/fr.json';
import it from './locales/it.json';
import ptBR from './locales/pt-BR.json';
import ko from './locales/ko.json';

// A7: English only in the product UI. Locale files stay so an upstream merge
// does not fight missing imports; they are never selected.

export const supportedLanguages = [
  'en',
  'de',
  'es',
  'he',
  'zh-CN',
  'zh-HK',
  'ar',
  'te',
  'fr',
  'it',
  'pt-BR',
  'ko',
] as const;
export type SupportedLanguage = (typeof supportedLanguages)[number];

export const rtlLanguages: SupportedLanguage[] = ['he', 'ar'];

export const languageOptions: Array<{ value: SupportedLanguage; label: string; compactLabel: string }> = [
  { value: 'en', label: 'English', compactLabel: 'EN' },
  { value: 'de', label: 'Deutsch', compactLabel: 'DE' },
  { value: 'es', label: 'Español', compactLabel: 'ES' },
  { value: 'he', label: 'עברית', compactLabel: 'עברית' },
  { value: 'zh-CN', label: '简体中文', compactLabel: '简中' },
  { value: 'zh-HK', label: '繁體中文', compactLabel: '繁中' },
  { value: 'ar', label: 'العربية', compactLabel: 'AR' },
  { value: 'te', label: 'తెలుగు', compactLabel: 'TE' },
  { value: 'fr', label: 'Français', compactLabel: 'FR' },
  { value: 'it', label: 'Italiano', compactLabel: 'IT' },
  { value: 'pt-BR', label: 'Português (Brasil)', compactLabel: 'PT' },
  { value: 'ko', label: '한국어', compactLabel: 'KO' },
];

export function resolveSupportedLanguage(lang?: string): SupportedLanguage {
  const value = lang || 'en';
  const exact = supportedLanguages.find(supported => supported.toLowerCase() === value.toLowerCase());
  if (exact) return exact;

  const parts = value.toLowerCase().split('-');
  const base = parts[0];
  if (base === 'zh') {
    const subtags = new Set(parts.slice(1));
    if (subtags.has('hant') || subtags.has('hk') || subtags.has('mo') || subtags.has('tw')) return 'zh-HK';
    return 'zh-CN';
  }

  return supportedLanguages.find(supported => supported === base) ?? 'en';
}

try {
  localStorage.removeItem('openwa_language');
  localStorage.removeItem('i18nextLng');
} catch {
  /* private mode */
}

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    de: { translation: de },
    es: { translation: es },
    he: { translation: he },
    'zh-CN': { translation: zhCN },
    'zh-HK': { translation: zhHK },
    ar: { translation: ar },
    te: { translation: te },
    fr: { translation: fr },
    it: { translation: it },
    'pt-BR': { translation: ptBR },
    ko: { translation: ko },
  },
  lng: 'en',
  fallbackLng: 'en',
  supportedLngs: ['en'],
  nonExplicitSupportedLngs: false,
  interpolation: { escapeValue: false },
  react: { useSuspense: false },
});

function applyDirection(lang: string) {
  const resolved = resolveSupportedLanguage(lang);
  const dir = rtlLanguages.includes(resolved) ? 'rtl' : 'ltr';
  if (typeof document !== 'undefined') {
    document.documentElement.lang = resolved;
    document.documentElement.dir = dir;
  }
}

applyDirection(i18n.language);
i18n.on('languageChanged', applyDirection);

export default i18n;
