import { useEffect } from 'react';

/**
 * Custom hook to set document title dynamically.
 * Automatically appends " | A7 Group" suffix.
 */
export function useDocumentTitle(title: string) {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${title} | A7 Group`;

    return () => {
      document.title = previousTitle;
    };
  }, [title]);
}
