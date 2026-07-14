import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const jsonPath = path.join(__dirname, "서울시_아파트_단지_목록_한국부동산원_20250918.json");
const outputPath = path.join(__dirname, "서울시_아파트_단지_목록_한국부동산원_20250918.xlsx");
const previewPath = path.join(__dirname, "preview.png");

const data = JSON.parse(await fs.readFile(jsonPath, "utf8"));
const workbook = Workbook.create();
const sheet = workbook.worksheets.add("서울 아파트 단지");
sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);

const parseInteger = (value) => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number.parseInt(String(value).replace(/,/g, ""), 10);
  return Number.isFinite(parsed) ? parsed : null;
};

const parseDate = (value) => {
  if (!value) return null;
  const [year, month, day] = String(value).split("-").map(Number);
  if (!year || !month || !day) return String(value);
  return new Date(Date.UTC(year, month - 1, day));
};

const rows = data.rows.map((row) => [
  String(row["단지고유번호"] ?? ""),
  String(row["필지고유번호"] ?? ""),
  row["시도"] ?? "",
  row["자치구"] ?? "",
  row["법정동"] ?? "",
  row["지번"] ?? "",
  row["주소"] ?? "",
  row["대표단지명"] ?? "",
  row["단지명_공시가격"] ?? "",
  row["단지명_건축물대장"] ?? "",
  row["단지명_도로명주소"] ?? "",
  String(row["단지종류코드"] ?? ""),
  row["단지종류명"] ?? "",
  parseInteger(row["동수"]),
  parseInteger(row["세대수"]),
  parseDate(row["사용승인일"]),
  row["원천데이터"] ?? "",
]);

const matrix = [data.headers, ...rows];
sheet.getRangeByIndexes(0, 0, matrix.length, 2).format.numberFormat = "@";
sheet.getRangeByIndexes(0, 11, matrix.length, 2).format.numberFormat = "@";
sheet.getRangeByIndexes(0, 0, matrix.length, matrix[0].length).values = matrix;

const rowCount = matrix.length;
const colCount = 17;
const lastRow = rowCount;
const tableRange = `A1:Q${lastRow}`;
const table = sheet.tables.add(tableRange, true, "SeoulApartmentComplexes");
table.style = "TableStyleMedium2";
table.showFilterButton = true;

const header = sheet.getRange("A1:Q1");
header.format.fill.color = "#1F4E78";
header.format.font.color = "#FFFFFF";
header.format.font.bold = true;
header.format.horizontalAlignment = "center";
header.format.verticalAlignment = "center";
header.format.rowHeight = 24;

sheet.getRange(`A2:B${lastRow}`).format.numberFormat = "@";
sheet.getRange(`L2:M${lastRow}`).format.numberFormat = "@";
sheet.getRange(`N2:O${lastRow}`).format.numberFormat = "#,##0";
sheet.getRange(`P2:P${lastRow}`).format.numberFormat = "yyyy-mm-dd";
sheet.getRange(`A1:Q${lastRow}`).format.font.name = "맑은 고딕";
sheet.getRange(`A1:Q${lastRow}`).format.font.size = 10;
sheet.getRange(`A2:Q${lastRow}`).format.verticalAlignment = "center";
sheet.getRange(`N2:O${lastRow}`).format.horizontalAlignment = "right";

const widths = [
  22, 28, 12, 12, 12, 14, 34, 28, 28, 28, 28, 12, 12, 8, 10, 12, 42,
];
for (let i = 0; i < widths.length; i += 1) {
  sheet.getRangeByIndexes(0, i, lastRow, 1).format.columnWidth = widths[i];
}

sheet.getRange(`A1:Q${lastRow}`).format.borders = {
  insideHorizontal: { style: "thin", color: "#E5E7EB" },
  top: { style: "thin", color: "#B7C9D6" },
  bottom: { style: "thin", color: "#B7C9D6" },
};

const inspect = await workbook.inspect({
  kind: "table",
  range: "서울 아파트 단지!A1:Q8",
  include: "values",
  tableMaxRows: 8,
  tableMaxCols: 17,
  maxChars: 4000,
});
console.log(inspect.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
  maxChars: 2000,
});
console.log(errors.ndjson);

const preview = await workbook.render({
  sheetName: "서울 아파트 단지",
  range: "A1:Q30",
  scale: 1,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);
