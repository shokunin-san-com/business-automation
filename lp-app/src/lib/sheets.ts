/**
 * Google Sheets TypeScript client — used by all API routes.
 *
 * Auth:
 *   - In production (Vercel): reads GOOGLE_SERVICE_ACCOUNT_JSON env var
 *   - In local dev: falls back to ../credentials/service_account.json
 */

import { google, sheets_v4 } from "googleapis";
import fs from "fs";
import path from "path";

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

function getAuth() {
  // 1. Try env var (Vercel / Cloud Run)
  const saJson = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  if (saJson) {
    const parsed = JSON.parse(saJson);
    return new google.auth.GoogleAuth({
      credentials: parsed,
      scopes: ["https://www.googleapis.com/auth/spreadsheets"],
    });
  }

  // 2. Fallback: local file
  const localPath = path.join(process.cwd(), "..", "credentials", "service_account.json");
  if (fs.existsSync(localPath)) {
    return new google.auth.GoogleAuth({
      keyFile: localPath,
      scopes: ["https://www.googleapis.com/auth/spreadsheets"],
    });
  }

  throw new Error("No Google credentials found (GOOGLE_SERVICE_ACCOUNT_JSON or local file)");
}

let _sheets: sheets_v4.Sheets | null = null;

function getSheetsClient(): sheets_v4.Sheets {
  if (!_sheets) {
    const auth = getAuth();
    _sheets = google.sheets({ version: "v4", auth });
  }
  return _sheets;
}

function getSpreadsheetId(): string {
  const id = process.env.GOOGLE_SHEETS_ID || process.env.NEXT_PUBLIC_GOOGLE_SHEETS_ID || "";
  if (!id) throw new Error("GOOGLE_SHEETS_ID not set");
  return id;
}

// ---------------------------------------------------------------------------
// Read helpers
// ---------------------------------------------------------------------------

/**
 * Get all rows from a sheet, returning array of objects keyed by header row.
 */
export async function getAllRows(sheetName: string): Promise<Record<string, string>[]> {
  const sheets = getSheetsClient();
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId: getSpreadsheetId(),
    range: `${sheetName}`,
  });

  const rows = res.data.values;
  if (!rows || rows.length < 2) return [];

  const headers = rows[0];
  return rows.slice(1).map((row) => {
    const obj: Record<string, string> = {};
    headers.forEach((h, i) => {
      obj[h] = row[i] || "";
    });
    return obj;
  });
}

/**
 * Get rows matching a column value.
 */
export async function getRowsByColumn(
  sheetName: string,
  column: string,
  value: string,
): Promise<Record<string, string>[]> {
  const all = await getAllRows(sheetName);
  return all.filter((row) => row[column] === value);
}

/**
 * Count rows in a sheet (excluding header).
 */
export async function countRows(sheetName: string): Promise<number> {
  const sheets = getSheetsClient();
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId: getSpreadsheetId(),
    range: `${sheetName}`,
  });
  const rows = res.data.values;
  if (!rows || rows.length < 2) return 0;
  return rows.length - 1;
}

// ---------------------------------------------------------------------------
// Write helpers
// ---------------------------------------------------------------------------

/**
 * Update a specific cell by finding the row where `keyColumn` == `keyValue`,
 * then setting `targetColumn` to `newValue`.
 */
export async function updateCell(
  sheetName: string,
  keyColumn: string,
  keyValue: string,
  targetColumn: string,
  newValue: string,
): Promise<boolean> {
  const sheets = getSheetsClient();
  const spreadsheetId = getSpreadsheetId();

  // Read all data to find headers and row index
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: sheetName,
  });

  const rows = res.data.values;
  if (!rows || rows.length < 2) return false;

  const headers = rows[0];
  const keyIdx = headers.indexOf(keyColumn);
  const targetIdx = headers.indexOf(targetColumn);
  if (keyIdx === -1 || targetIdx === -1) return false;

  // Find row (1-indexed, +1 for header)
  const rowIndex = rows.findIndex((row, i) => i > 0 && row[keyIdx] === keyValue);
  if (rowIndex === -1) return false;

  // Convert column index to A1 notation
  const colLetter = String.fromCharCode(65 + targetIdx);
  const cellRange = `${sheetName}!${colLetter}${rowIndex + 1}`;

  await sheets.spreadsheets.values.update({
    spreadsheetId,
    range: cellRange,
    valueInputOption: "RAW",
    requestBody: { values: [[newValue]] },
  });

  return true;
}

/**
 * Append rows to a sheet.
 */
export async function appendRows(
  sheetName: string,
  rows: string[][],
): Promise<void> {
  const sheets = getSheetsClient();
  await sheets.spreadsheets.values.append({
    spreadsheetId: getSpreadsheetId(),
    range: `${sheetName}!A1`,
    valueInputOption: "RAW",
    requestBody: { values: rows },
  });
}

/**
 * Ensure a sheet (tab) exists within the spreadsheet. If not, create it with headers.
 */
export async function ensureSheetExists(
  sheetName: string,
  headers: string[],
): Promise<void> {
  const sheets = getSheetsClient();
  const spreadsheetId = getSpreadsheetId();

  // List existing sheets
  const meta = await sheets.spreadsheets.get({
    spreadsheetId,
    fields: "sheets.properties.title",
  });

  const existing = meta.data.sheets?.map((s) => s.properties?.title) || [];

  if (!existing.includes(sheetName)) {
    await sheets.spreadsheets.batchUpdate({
      spreadsheetId,
      requestBody: {
        requests: [{ addSheet: { properties: { title: sheetName } } }],
      },
    });

    // Write headers
    await sheets.spreadsheets.values.update({
      spreadsheetId,
      range: `${sheetName}!A1`,
      valueInputOption: "RAW",
      requestBody: { values: [headers] },
    });
  }
}
