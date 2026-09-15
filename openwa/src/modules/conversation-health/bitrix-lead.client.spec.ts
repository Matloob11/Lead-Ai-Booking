import { ConfigService } from '@nestjs/config';
import { BitrixLeadClient } from './bitrix-lead.client';

describe('BitrixLeadClient findOrCreateLead', () => {
  const originalFetch = global.fetch;
  let client: BitrixLeadClient;
  let calls: Array<{ method: string; body: Record<string, unknown> | undefined }>;

  beforeEach(() => {
    calls = [];
    process.env.BITRIX_WEBHOOK_BASE = 'https://crm.example.com/rest/1/tok';
    process.env.BITRIX_OWNER_DATA_TYPE_ID = '1042';
    client = new BitrixLeadClient({ get: () => undefined } as unknown as ConfigService);

    global.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = url.split('/').pop()?.replace('.json', '') || '';
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined;
      calls.push({ method, body });

      if (method === 'crm.duplicate.findbycomm') {
        const leadIds = (global as unknown as { __leads?: string[] }).__leads || [];
        return new Response(JSON.stringify({ result: { LEAD: leadIds } }), { status: 200 });
      }
      if (method === 'crm.item.list') {
        const ownerIds = (global as unknown as { __owners?: string[] }).__owners || [];
        return new Response(
          JSON.stringify({ result: { items: ownerIds.map(id => ({ id })) } }),
          { status: 200 },
        );
      }
      if (method === 'crm.lead.add') {
        return new Response(JSON.stringify({ result: 99901 }), { status: 200 });
      }
      return new Response(JSON.stringify({ result: {} }), { status: 200 });
    }) as typeof fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
    delete (global as unknown as { __leads?: string[] }).__leads;
    delete (global as unknown as { __owners?: string[] }).__owners;
    delete process.env.BITRIX_WEBHOOK_BASE;
    delete process.env.BITRIX_OWNER_DATA_TYPE_ID;
  });

  it('uses existing CRM lead when phone matches', async () => {
    (global as unknown as { __leads: string[] }).__leads = ['72122'];
    const t = await client.findOrCreateLead('971508512115', 'test');
    expect(t).toEqual({ id: '72122', entityType: 'lead', created: false, kind: 'lead' });
    expect(calls.some(c => c.method === 'crm.item.list')).toBe(false);
    expect(calls.some(c => c.method === 'crm.lead.add')).toBe(false);
  });

  it('uses Owner Data when no lead but SPA phone matches', async () => {
    (global as unknown as { __leads: string[] }).__leads = [];
    (global as unknown as { __owners: string[] }).__owners = ['80840'];
    const t = await client.findOrCreateLead('971559525201', 'Ahsan');
    expect(t).toEqual({
      id: '80840',
      entityType: 'DYNAMIC_1042',
      created: false,
      kind: 'owner_data',
    });
    expect(calls.some(c => c.method === 'crm.lead.add')).toBe(false);
  });

  it('creates WhatsApp Lead when neither lead nor Owner Data matches', async () => {
    (global as unknown as { __leads: string[] }).__leads = [];
    (global as unknown as { __owners: string[] }).__owners = [];
    const t = await client.findOrCreateLead('971500000001', 'new');
    expect(t).toEqual({ id: '99901', entityType: 'lead', created: true, kind: 'lead' });
  });

  it('builds Owner Data detail URL', () => {
    expect(client.entityUrl('80840', 'DYNAMIC_1042')).toContain('/crm/type/1042/details/80840/');
  });
});
