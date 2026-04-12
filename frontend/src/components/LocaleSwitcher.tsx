'use client';

import { useLocale } from 'next-intl';
import { useRouter, usePathname } from '@/i18n/navigation';

export default function LocaleSwitcher() {
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();

  const switchLocale = (newLocale: string) => {
    router.replace(pathname, { locale: newLocale });
  };

  return (
    <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
      <button
        onClick={() => switchLocale('hu')}
        aria-label="Magyar nyelv"
        style={{
          padding: '0.35rem 0.75rem',
          borderRadius: '6px',
          border: locale === 'hu' ? '2px solid #3b82f6' : '1px solid #d1d5db',
          backgroundColor: locale === 'hu' ? '#3b82f6' : 'white',
          color: locale === 'hu' ? 'white' : '#374151',
          cursor: 'pointer',
          fontWeight: locale === 'hu' ? 'bold' : 'normal',
          fontSize: '0.85rem',
          transition: 'all 0.15s ease',
        }}
      >
        HU
      </button>
      <button
        onClick={() => switchLocale('en')}
        aria-label="English language"
        style={{
          padding: '0.35rem 0.75rem',
          borderRadius: '6px',
          border: locale === 'en' ? '2px solid #3b82f6' : '1px solid #d1d5db',
          backgroundColor: locale === 'en' ? '#3b82f6' : 'white',
          color: locale === 'en' ? 'white' : '#374151',
          cursor: 'pointer',
          fontWeight: locale === 'en' ? 'bold' : 'normal',
          fontSize: '0.85rem',
          transition: 'all 0.15s ease',
        }}
      >
        EN
      </button>
    </div>
  );
}
