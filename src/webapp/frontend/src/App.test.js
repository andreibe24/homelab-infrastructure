import { describe, expect, it } from 'vitest';

import { fetchHealth, render } from './App.js';

describe('render', () => {
  it('renders payload rows', () => {
    const html = render({ ok: true, source: '/api/health', payload: { status: 'ok' } });
    expect(html).toContain('backend reachable');
    expect(html).toContain('status');
  });
});

describe('fetchHealth', () => {
  it('returns the parsed payload on success', async () => {
    const stub = async () => ({ ok: true, json: async () => ({ status: 'ok', protocol: 'HTTP/3' }) });
    const state = await fetchHealth('/api', stub);
    expect(state.ok).toBe(true);
    expect(state.payload.protocol).toBe('HTTP/3');
  });

  it('reports transport errors instead of throwing', async () => {
    const stub = async () => {
      throw new Error('boom');
    };
    const state = await fetchHealth('/api', stub);
    expect(state.ok).toBe(false);
    expect(state.error).toContain('boom');
  });
});
