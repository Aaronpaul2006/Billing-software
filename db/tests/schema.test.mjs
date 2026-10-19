// Executable checks of db/schema.sql: tenant isolation, document lifecycle,
// settlements and audit trail. Runs on PGlite (PostgreSQL 17 compiled to WASM).
// Usage: npm test   (from db/tests)

import { PGlite } from '@electric-sql/pglite';
import { citext } from '@electric-sql/pglite/contrib/citext';
import { pg_trgm } from '@electric-sql/pglite/contrib/pg_trgm';
import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';

const schemaPath = process.argv[2];
const db = await PGlite.create({ extensions: { citext, pg_trgm } });
await db.exec(readFileSync(schemaPath, 'utf8'));
console.log('schema loaded');

let pass = 0, fail = 0;
const ok = (name) => { pass++; console.log('  PASS', name); };
const bad = (name, e) => { fail++; console.log('  FAIL', name, e ?? ''); };

// Run fn as the application role inside one transaction with tenant/user context.
async function as(tenant, user, fn) {
  return db.transaction(async (tx) => {
    await tx.exec('SET LOCAL ROLE billing_app');
    await tx.query(`SELECT set_config('app.tenant_id', $1, true), set_config('app.user_id', $2, true)`,
      [tenant ?? '', user ?? '']);
    return fn(tx);
  });
}
async function expectOk(name, tenant, user, fn) {
  try { const r = await as(tenant, user, fn); ok(name); return r; } catch (e) { bad(name, e.message); }
}
async function expectErr(name, tenant, user, fn, pattern) {
  try { await as(tenant, user, fn); bad(name, '(no error raised)'); }
  catch (e) { pattern.test(e.message) ? ok(`${name}  → ${e.message.split('\n')[0]}`) : bad(name, e.message); }
}

// ---------- seed two tenants through the app role, exactly as the API would ----------
const uA = randomUUID(), uB = randomUUID(), tA = randomUUID(), tB = randomUUID();
const ids = { A: {}, B: {} };

async function seedTenant(key, t, u, email, gstin, state) {
  const k = ids[key];
  k.reg = randomUUID(); k.party = randomUUID(); k.project = randomUUID(); k.series = randomUUID(); k.doc = randomUUID();
  await as(t, u, async (tx) => {
    await tx.query(`INSERT INTO users (id, email, password_hash, full_name) VALUES ($1, $2, 'argon2id$x', 'User ' || $3)`, [u, email, key]);
    await tx.query(`INSERT INTO tenants (id, legal_name) VALUES ($1, 'Builder ' || $2)`, [t, key]);
    await tx.query(`INSERT INTO memberships (tenant_id, user_id, role) VALUES ($1, $2, 'OWNER')`, [t, u]);
    await tx.query(`INSERT INTO gst_registrations (id, tenant_id, registration_type, gstin, state_code, legal_name, address, is_default)
                    VALUES ($1, $2, 'REGULAR', $3, $4, 'Builder', '{}', true)`, [k.reg, t, gstin, state]);
    await tx.query(`INSERT INTO parties (id, tenant_id, display_name, gst_treatment, state_code, created_by)
                    VALUES ($1, $2, 'Client of ' || $3, 'UNREGISTERED', $4, $5)`, [k.party, t, key, state, u]);
    await tx.query(`INSERT INTO projects (id, tenant_id, code, name, client_party_id, gst_registration_id, site_state_code, retention_pct, created_by)
                    VALUES ($1, $2, 'P1', 'Villa', $3, $4, $5, 5, $6)`, [k.project, t, k.party, k.reg, state, u]);
    await tx.query(`INSERT INTO document_series (id, tenant_id, gst_registration_id, doc_type, fy_start_year, prefix)
                    VALUES ($1, $2, $3, 'TAX_INVOICE', 2026, 'INV/')`, [k.series, t, k.reg]);
    await tx.query(`INSERT INTO documents (id, tenant_id, doc_type, gst_registration_id, doc_date, party_id, project_id,
                      place_of_supply, supply_type, created_by)
                    VALUES ($1, $2, 'TAX_INVOICE', $3, '2026-10-19', $4, $5, $6, 'INTRA_STATE', $7)`,
                    [k.doc, t, k.reg, k.party, k.project, state, u]);
  });
}
await seedTenant('A', tA, uA, 'a@example.com', '32ABCDE1234F1Z5', '32');
await seedTenant('B', tB, uB, 'b@example.com', '29ABCDE1234F1Z5', '29');
console.log('seeded tenants A and B via billing_app');

const addLine = (tx, k, t) => tx.query(
  `INSERT INTO document_lines (tenant_id, document_id, line_no, description, sac_hsn, quantity, rate, taxable_value,
     gst_rate, cgst_amount, sgst_amount, line_total)
   VALUES ($1, $2, 1, 'RCC work', '9954', 10, 1000, 10000, 18, 900, 900, 11800)`, [t, k.doc]);
const setTotals = (tx, k, subtotal = 10000) => tx.query(
  `UPDATE documents SET subtotal = $2::numeric, cgst_amount = 900, sgst_amount = 900, grand_total = $2::numeric + 1800,
     retention_amount = 500, income_tax_tds_amount = 200, net_receivable = $2::numeric + 1800 - 700 WHERE id = $1`, [k.doc, subtotal]);
const issue = (tx, k, u, num = 'INV/0001') => tx.query(
  `UPDATE documents SET status = 'ISSUED', series_id = $2, doc_number = $3, issued_at = now(), issued_by = $4,
     supplier_snapshot = '{}', party_snapshot = '{}' WHERE id = $1`, [k.doc, k.series, num, u]);

console.log('\n1. Tenant isolation');
await expectOk('tenant A sees only its own parties', tA, uA, async (tx) => {
  const r = await tx.query(`SELECT tenant_id FROM parties`);
  if (r.rows.length !== 1 || r.rows[0].tenant_id !== tA) throw new Error(JSON.stringify(r.rows));
});
await expectOk('no tenant context → zero rows (fail closed)', null, uA, async (tx) => {
  const r = await tx.query(`SELECT count(*)::int AS n FROM documents`);
  if (r.rows[0].n !== 0) throw new Error(`saw ${r.rows[0].n}`);
});
await expectOk('tenant A cannot read B document by id', tA, uA, async (tx) => {
  const r = await tx.query(`SELECT * FROM documents WHERE id = $1`, [ids.B.doc]);
  if (r.rows.length) throw new Error('leaked');
});
await expectErr('tenant A cannot insert a row tagged with tenant B', tA, uA,
  (tx) => tx.query(`INSERT INTO parties (tenant_id, display_name, gst_treatment, created_by) VALUES ($1, 'x', 'CONSUMER', $2)`, [tB, uA]),
  /row-level security/);
await expectOk('tenant A UPDATE of B rows affects nothing', tA, uA, async (tx) => {
  const r = await tx.query(`UPDATE parties SET display_name = 'hacked' WHERE id = $1`, [ids.B.party]);
  if (r.affectedRows !== 0) throw new Error('updated foreign row');
});
await expectErr('cross-tenant reference blocked by composite FK', tA, uA,
  (tx) => tx.query(`INSERT INTO documents (tenant_id, doc_type, gst_registration_id, doc_date, party_id, place_of_supply, supply_type, created_by)
                    VALUES ($1, 'QUOTATION', $2, '2026-10-19', $3, '32', 'INTRA_STATE', $4)`, [tA, ids.A.reg, ids.B.party, uA]),
  /foreign key/);
await expectOk('login with no tenant: user sees own memberships and tenant names only', null, uA, async (tx) => {
  const m = await tx.query(`SELECT tenant_id FROM memberships`);
  const t = await tx.query(`SELECT id FROM tenants`);
  if (m.rows.length !== 1 || t.rows.length !== 1 || t.rows[0].id !== tA) throw new Error(JSON.stringify([m.rows, t.rows]));
});

console.log('\n2. Document lifecycle');
await expectErr('cannot issue with no lines', tA, uA, (tx) => issue(tx, ids.A, uA), /no lines/);
await expectErr('cannot create a document already ISSUED', tA, uA,
  (tx) => tx.query(`INSERT INTO documents (tenant_id, doc_type, status, gst_registration_id, doc_date, party_id, place_of_supply, supply_type, created_by)
                    VALUES ($1, 'QUOTATION', 'ISSUED', $2, '2026-10-19', $3, '32', 'INTRA_STATE', $4)`, [tA, ids.A.reg, ids.A.party, uA]),
  /created as DRAFT/);
await expectErr('line arithmetic is checked', tA, uA,
  (tx) => tx.query(`INSERT INTO document_lines (tenant_id, document_id, line_no, description, quantity, rate, taxable_value, line_total)
                    VALUES ($1, $2, 9, 'bad', 2, 100, 150, 150)`, [tA, ids.A.doc]), /check constraint/);
await expectErr('cannot issue when totals differ from lines', tA, uA, async (tx) => {
  await addLine(tx, ids.A, tA); await setTotals(tx, ids.A, 9999); await issue(tx, ids.A, uA);
}, /check constraint|do not match/);
await expectErr('IGST on an intra-state document is rejected', tA, uA,
  (tx) => tx.query(`UPDATE documents SET igst_amount = 100, grand_total = grand_total + 100 WHERE id = $1`, [ids.A.doc]),
  /check constraint/);
await expectOk('issue a correct invoice', tA, uA, async (tx) => {
  await addLine(tx, ids.A, tA); await setTotals(tx, ids.A); await issue(tx, ids.A, uA);
  const r = await tx.query(`SELECT fy_start_year, is_gst_document, net_receivable FROM documents WHERE id = $1`, [ids.A.doc]);
  const d = r.rows[0];
  if (d.fy_start_year !== 2026 || d.is_gst_document !== true || Number(d.net_receivable) !== 11100) throw new Error(JSON.stringify(d));
});
await expectErr('issued invoice cannot be edited', tA, uA,
  (tx) => tx.query(`UPDATE documents SET notes = 'changed' WHERE id = $1`, [ids.A.doc]), /cannot be edited/);
await expectErr('issued invoice cannot be deleted', tA, uA,
  (tx) => tx.query(`DELETE FROM documents WHERE id = $1`, [ids.A.doc]), /only drafts/);
await expectErr('lines of an issued invoice are frozen', tA, uA,
  (tx) => tx.query(`UPDATE document_lines SET description = 'x' WHERE document_id = $1`, [ids.A.doc]), /cannot be changed/);
await expectErr('duplicate invoice number in same FY rejected', tA, uA, async (tx) => {
  const d = randomUUID();
  await tx.query(`INSERT INTO documents (id, tenant_id, doc_type, gst_registration_id, doc_date, party_id, place_of_supply, supply_type, created_by)
                  VALUES ($1, $2, 'TAX_INVOICE', $3, '2027-01-05', $4, '32', 'INTRA_STATE', $5)`, [d, tA, ids.A.reg, ids.A.party, uA]);
  await addLine(tx, { doc: d }, tA); await setTotals(tx, { doc: d }); await issue(tx, { doc: d, series: ids.A.series }, uA, 'INV/0001');
}, /duplicate key/);
await expectErr('wrong supply_type for place of supply rejected at issue', tA, uA, async (tx) => {
  const d = randomUUID();
  await tx.query(`INSERT INTO documents (id, tenant_id, doc_type, gst_registration_id, doc_date, party_id, place_of_supply, supply_type, created_by)
                  VALUES ($1, $2, 'TAX_INVOICE', $3, '2026-10-19', $4, '29', 'INTRA_STATE', $5)`, [d, tA, ids.A.reg, ids.A.party, uA]);
  await addLine(tx, { doc: d }, tA); await setTotals(tx, { doc: d }); await issue(tx, { doc: d, series: ids.A.series }, uA, 'INV/0002');
}, /supply_type/);
await expectErr('bill of supply cannot carry GST', tA, uA,
  (tx) => tx.query(`INSERT INTO documents (tenant_id, doc_type, gst_registration_id, doc_date, party_id, place_of_supply, supply_type,
                      subtotal, cgst_amount, sgst_amount, grand_total, net_receivable, created_by)
                    VALUES ($1, 'BILL_OF_SUPPLY', $2, '2026-10-19', $3, '32', 'INTRA_STATE', 100, 9, 9, 118, 118, $4)`, [tA, ids.A.reg, ids.A.party, uA]),
  /check constraint/);

console.log('\n3. Payments & settlement');
const pay = randomUUID();
await expectOk('record payment and allocate 5000', tA, uA, async (tx) => {
  await tx.query(`INSERT INTO payments (id, tenant_id, party_id, payment_date, amount, mode, created_by)
                  VALUES ($1, $2, $3, '2026-10-20', 8000, 'UPI', $4)`, [pay, tA, ids.A.party, uA]);
  await tx.query(`INSERT INTO allocations (tenant_id, document_id, payment_id, amount, created_by) VALUES ($1, $2, $3, 5000, $4)`, [tA, ids.A.doc, pay, uA]);
  const r = await tx.query(`SELECT amount_settled FROM documents WHERE id = $1`, [ids.A.doc]);
  if (Number(r.rows[0].amount_settled) !== 5000) throw new Error(JSON.stringify(r.rows));
});
await expectErr('allocating more than the payment is rejected', tA, uA,
  (tx) => tx.query(`INSERT INTO allocations (tenant_id, document_id, payment_id, amount, created_by) VALUES ($1, $2, $3, 3500, $4)`,
    [tA, ids.A.doc, pay, uA]), /exceeds|duplicate key/);
await expectErr('app cannot write amount_settled directly', tA, uA,
  (tx) => tx.query(`UPDATE documents SET amount_settled = 0 WHERE id = $1`, [ids.A.doc]), /permission denied/);
await expectErr('cannot cancel an invoice that has settlements', tA, uA,
  (tx) => tx.query(`UPDATE documents SET status = 'CANCELLED', cancelled_at = now(), cancelled_by = $2, cancel_reason = 'x' WHERE id = $1`,
    [ids.A.doc, uA]), /check constraint/);
await expectOk('receivables view shows outstanding 6100 for A only', tA, uA, async (tx) => {
  const r = await tx.query(`SELECT tenant_id, outstanding FROM v_receivables`);
  if (r.rows.length !== 1 || r.rows[0].tenant_id !== tA || Number(r.rows[0].outstanding) !== 6100) throw new Error(JSON.stringify(r.rows));
});
await expectOk('billing summary view respects RLS', tB, uB, async (tx) => {
  const r = await tx.query(`SELECT * FROM v_billing_summary`);
  if (r.rows.length !== 0) throw new Error('B sees A billing: ' + JSON.stringify(r.rows));
});
await expectOk('unwind allocation then cancel', tA, uA, async (tx) => {
  await tx.query(`DELETE FROM allocations WHERE payment_id = $1`, [pay]);
  await tx.query(`UPDATE documents SET status = 'CANCELLED', cancelled_at = now(), cancelled_by = $2, cancel_reason = 'wrong client' WHERE id = $1`, [ids.A.doc, uA]);
});

console.log('\n4. Audit trail');
await expectOk('every change was audited with the acting user', tA, uA, async (tx) => {
  const r = await tx.query(`SELECT count(*)::int n, count(DISTINCT actor_user_id)::int actors, bool_and(tenant_id = $1) mine FROM audit_log`, [tA]);
  const x = r.rows[0];
  if (x.n < 10 || x.actors !== 1 || !x.mine) throw new Error(JSON.stringify(x));
  console.log(`      (${x.n} audit rows for tenant A)`);
});
await expectOk('tenant B cannot read A audit rows', tB, uB, async (tx) => {
  const r = await tx.query(`SELECT count(*)::int n FROM audit_log WHERE tenant_id = $1`, [tA]);
  if (r.rows[0].n !== 0) throw new Error('leak');
});
await expectErr('app cannot delete audit rows', tA, uA, (tx) => tx.query(`DELETE FROM audit_log`), /permission denied/);
await expectErr('app cannot forge audit rows', tA, uA,
  (tx) => tx.query(`INSERT INTO audit_log (tenant_id, action, table_name, row_id) VALUES ($1, 'INSERT', 'x', $1)`, [tA]), /permission denied/);
try { await db.query(`UPDATE audit_log SET actor_user_id = NULL`); bad('even the owner cannot rewrite audit rows', '(no error)'); }
catch (e) { /append-only/.test(e.message) ? ok('even the owner/superuser cannot rewrite audit rows') : bad('owner audit rewrite', e.message); }
await expectErr('payments cannot be hard-deleted (void instead)', tA, uA,
  (tx) => tx.query(`DELETE FROM payments WHERE id = $1`, [pay]), /permission denied/);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
