const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  AlignmentType, HeadingLevel, Footer, PageNumber, LevelFormat,
} = require("docx");

const OUT = process.argv[2];
const DATA = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const VERSION = DATA._version;
const BASE = "http://192.168.11.216:4300/api";

// ----------------------------------------------------------------------------- look
const NAVY = "1F3A5F", BLUE = "2B6CB0", GREY = "6B7280", LINE = "D1D5DB", CODEBG = "F3F4F6", HEADBG = "1F3A5F", ALT = "F8FAFC";
const PAGE_W = 11906, PAGE_H = 16838, MARGIN = 1134;            // A4, 2 cm margins
const W = PAGE_W - 2 * MARGIN;                                    // 9638 content width (DXA)
const FONT = "Calibri", MONO = "Consolas";

// ----------------------------------------------------------------------------- helpers
function runs(text, base = {}) {
  const out = [];
  for (const part of text.split(/(\*\*[^*]+\*\*|`[^`]+`)/)) {
    if (!part) continue;
    if (part.startsWith("**")) out.push(new TextRun({ text: part.slice(2, -2), bold: true, font: FONT, ...base }));
    else if (part.startsWith("`")) out.push(new TextRun({ text: part.slice(1, -1), font: MONO, size: (base.size || 21) - 2, shading: { type: ShadingType.CLEAR, fill: "EEF1F5", color: "auto" }, color: base.color }));
    else out.push(new TextRun({ text: part, font: FONT, ...base }));
  }
  return out;
}
const P = (text, o = {}) => new Paragraph({ children: runs(text, o.run || {}), spacing: { after: o.after ?? 120, before: o.before ?? 0 }, alignment: o.align, keepNext: o.keepNext, indent: o.indent });
const H1 = (text, group) => [
  ...(group ? [new Paragraph({ pageBreakBefore: true, spacing: { after: 40 }, children: [new TextRun({ text: group.toUpperCase(), font: FONT, size: 17, bold: true, color: GREY, characterSpacing: 40 })] })] : []),
  new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: !group, spacing: { before: group ? 0 : 0, after: 120 }, keepNext: true,
    border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: BLUE, space: 4 } }, children: [new TextRun({ text, font: FONT, size: 34, bold: true, color: NAVY })] }),
];
const H2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 150, after: 60 }, keepNext: true, children: [new TextRun({ text, font: FONT, size: 24, bold: true, color: BLUE })] });
const bullets = (items) => items.map((t) => new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 60 }, children: runs(t) }));

function code(text) {
  const lines = text.split("\n");
  return lines.map((line, i) => new Paragraph({
    children: [new TextRun({ text: line.length ? line : " ", font: MONO, size: 16 })],
    shading: { type: ShadingType.CLEAR, fill: CODEBG, color: "auto" },
    spacing: { after: i === lines.length - 1 ? 100 : 0, line: 225 },
    indent: { left: 100, right: 100 }, keepLines: true, keepNext: i < lines.length - 1,
  }));
}

const border = { style: BorderStyle.SINGLE, size: 4, color: LINE };
const borders = { top: border, bottom: border, left: border, right: border };
function table(headers, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  const cell = (t, w, head, i) => new TableCell({
    width: { size: w, type: WidthType.DXA }, borders,
    shading: head ? { type: ShadingType.CLEAR, fill: HEADBG, color: "auto" } : (i % 2 ? { type: ShadingType.CLEAR, fill: ALT, color: "auto" } : undefined),
    margins: { top: 35, bottom: 35, left: 90, right: 90 },
    children: [new Paragraph({ spacing: { after: 0 }, children: runs(t, head ? { bold: true, color: "FFFFFF", size: 19 } : { size: 19 }) })],
  });
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: [
      ...(headers ? [new TableRow({ tableHeader: true, cantSplit: true, children: headers.map((h, k) => cell(h, widths[k], true, 0)) })] : []),
      ...rows.map((r, i) => new TableRow({ cantSplit: true, children: r.map((t, k) => cell(String(t), widths[k], false, i)) })),
    ],
  });
}
const gap = (after = 60) => new Paragraph({ spacing: { after }, children: [] });

// ----------------------------------------------------------------------------- common text
const ERR = {
  validation_error: ["422", "A field is missing, has the wrong type, or breaks a rule (for example T or P not above 0, lists of different length, a negative or duplicate entry). `error.details` lists each field."],
  unknown_component: ["422", "A name or CAS number is not recognised. `error.details.component` names it. Use the CAS number instead."],
  flash_failed: ["422", "The equilibrium calculation did not work for this state. Check the conditions and composition."],
  property_unavailable: ["422", "Data needed for a component is missing. `error.details.components` lists them."],
  water_required: ["422", "The mixture does not contain water. Add `\"water\"` or `\"7732-18-5\"`, or use the EOS Stream API."],
  fit_failed: ["422", "The data cannot be fitted: fewer different opening values than the degree needs. `error.details` gives the numbers."],
  calculation_timeout: ["504", "The calculation took longer than 30 seconds."],
};
const errRows = (codes, special = {}) => codes.map((c) => [`\`${c}\``, ERR[c][0], special[c] || ERR[c][1]]);
const errTable = (codes, special) => table(["Error code", "HTTP", "When it occurs here"], errRows(codes, special), [2300, 700, 6638]);

const COMPOSITION_REQ = "The request is the common one described in section 2: `T` (K), `P` (Pa), `components` and `zs`.";
const WH_NOTE = "Example mixture: water 50 mol % and hexane 50 mol % at 300 K and 101325 Pa.";
const WH_CAPTION = WH_NOTE + " At this state the model finds a single liquid, so vapor values are null.";
const WH_CAPTION_EOS = WH_NOTE + " At this state the mixture is two liquid phases.";
const API_SPECIFIC_ERRORS = ["water_required", "fit_failed"];

// ----------------------------------------------------------------------------- the API pages
const apis = [
  {
    n: 4, group: "Property APIs", title: "Heat capacity", method: "POST", path: "/cp_calc",
    purpose: "Heat capacity of the liquid phase, the vapor phase and the whole mixture, together with the phase fractions, from a vapor–liquid flash at the given T and P.",
    req: COMPOSITION_REQ,
    fields: [["`Cp_liquid`", "number or null", "J/mol/K", "Liquid-phase heat capacity. null if there is no liquid."],
      ["`Cp_vapor`", "number or null", "J/mol/K", "Vapor-phase heat capacity (ideal-gas). null if there is no vapor."],
      ["`Cp_mix`", "number", "J/mol/K", "Fraction-weighted mixture heat capacity."],
      ["`Vapor_fraction`", "number", "mole fraction", "Vapor fraction (0 to 1)."],
      ["`Liquid_fraction`", "number", "mole fraction", "Liquid fraction (1 − vapor fraction)."]],
    notes: [WH_NOTE + " This state is a single liquid, so the vapor values are null.", "A phase that does not exist is null, never 0."],
    errors: ["validation_error", "unknown_component", "flash_failed", "property_unavailable", "calculation_timeout"],
  },
  {
    n: 5, group: "Property APIs", title: "Density", method: "POST", path: "/density_calc",
    purpose: "Density of the mixture at the given T and P.",
    req: COMPOSITION_REQ,
    fields: [["`rho_mix`", "number", "kg/m³", "Mixture density."],
      ["`phase`", "string or null", "–", "Phase state: `g` gas, `l` liquid, `l/g` two-phase."]],
    notes: [WH_NOTE, "For methane/ethane 50/50 at 423.15 K and 29411.81 Pa the result is 0.1927403 kg/m³ with phase `g`."],
    errors: ["validation_error", "unknown_component", "property_unavailable", "calculation_timeout"],
  },
  {
    n: 6, group: "Property APIs", title: "Molecular weight", method: "POST", path: "/mw_calc",
    purpose: "Molecular weight of the liquid phase, the vapor phase and the whole mixture.",
    req: COMPOSITION_REQ,
    fields: [["`MW_liquid`", "number or null", "g/mol", "Liquid phase. null if there is no liquid."],
      ["`MW_vapor`", "number or null", "g/mol", "Vapor phase. null if there is no vapor."],
      ["`MW_avg`", "number", "g/mol", "Overall mixture."]],
    notes: [WH_NOTE],
    errors: ["validation_error", "unknown_component", "flash_failed", "property_unavailable", "calculation_timeout"],
  },
  {
    n: 7, group: "Property APIs", title: "Vapor fraction", method: "POST", path: "/vf_calc",
    purpose: "How much of the mixture is vapor and how much is liquid at the given T and P.",
    req: COMPOSITION_REQ,
    fields: [["`Vapor_fraction`", "number", "mole fraction", "0 = all liquid, 1 = all vapor."],
      ["`Liquid_fraction`", "number", "mole fraction", "1 − vapor fraction."]],
    notes: [WH_NOTE, "Mole fractions that do not add up to 1 are rescaled; `meta.zs_normalized` is then true."],
    errors: ["validation_error", "unknown_component", "flash_failed", "calculation_timeout"],
  },
  {
    n: 8, group: "Property APIs", title: "Heat capacity: vapor, aqueous, organic", method: "POST", path: "/triphase_cp_calc",
    purpose: "Heat capacity of the vapor, aqueous (water) and organic phases of a mixture that contains water.",
    req: COMPOSITION_REQ + " **The mixture must contain water.**",
    fields: [["`Cp_aqueous`", "number or null", "J/mol/K", "null if there is no liquid water."],
      ["`Cp_organic`", "number or null", "J/mol/K", "null if there is no organic liquid."],
      ["`Cp_vapor`", "number or null", "J/mol/K", "null if there is no vapor."],
      ["`Cp_mix`", "number", "J/mol/K", "Weighted mixture heat capacity."]],
    notes: ["The liquid is split by approximation: **aqueous** = water, **organic** = all other components. This suits water and hydrocarbons that do not mix; for a rigorous split use the EOS Stream API.", WH_NOTE],
    errors: ["validation_error", "unknown_component", "water_required", "flash_failed", "calculation_timeout"],
    errExample: '{\n  "status": "error",\n  "error": {\n    "code": "water_required",\n    "message": "Triphase endpoints require water in the mixture (use \'water\' or \'7732-18-5\').",\n    "details": null\n  },\n  "request_id": "a1b2c3d4e5f6"\n}',
  },
  {
    n: 9, group: "Property APIs", title: "Molecular weight: vapor, aqueous, organic", method: "POST", path: "/triphase_mw_calc",
    purpose: "Molecular weight of the vapor, aqueous and organic phases of a mixture that contains water.",
    req: COMPOSITION_REQ + " **The mixture must contain water.**",
    fields: [["`MW_aqueous`", "number or null", "g/mol", "Water. null if there is no liquid water."],
      ["`MW_organic`", "number or null", "g/mol", "null if there is no organic liquid."],
      ["`MW_vapor`", "number or null", "g/mol", "null if there is no vapor."],
      ["`MW_mix`", "number", "g/mol", "Overall mixture."]],
    notes: ["Same aqueous / organic split as section 8.", WH_NOTE],
    errors: ["validation_error", "unknown_component", "water_required", "flash_failed", "calculation_timeout"],
  },
  {
    n: 10, group: "Property APIs", title: "Phase fractions: vapor, aqueous, organic", method: "POST", path: "/triphase_vf_calc",
    purpose: "How the total mixture divides into vapor, aqueous and organic phases.",
    req: COMPOSITION_REQ + " **The mixture must contain water.**",
    fields: [["`vapor_fraction`", "number", "mole fraction", "Share of the total mixture that is vapor."],
      ["`aqueous_fraction`", "number", "mole fraction", "Share of the total mixture that is aqueous liquid."],
      ["`organic_fraction`", "number", "mole fraction", "Share of the total mixture that is organic liquid."],
      ["`liquid_fraction`", "number", "mole fraction", "Aqueous plus organic."],
      ["`water_in_liquid`", "number", "mole fraction", "Water share within the liquid."],
      ["`organic_in_liquid`", "number", "mole fraction", "Non-water share within the liquid."]],
    notes: ["vapor + aqueous + organic fractions add up to 1.", "Same aqueous / organic split as section 8.", WH_NOTE],
    errors: ["validation_error", "unknown_component", "water_required", "flash_failed", "calculation_timeout"],
  },
  {
    n: 11, group: "EOS Stream API", title: "Stream properties", method: "POST", path: "/eos_stream_calc",
    purpose: "The complete result for a stream in one call, from a Peng-Robinson equation of state with a three-phase flash: the phase situation, and for every phase that exists its fraction, molecular weight, heat capacity and density, plus the mixture values. Water is optional.",
    req: COMPOSITION_REQ + " Components with a mole fraction of 0 are skipped.",
    fields: [["`case`", "string", "–", "`vapor-only`, `liquid-only (single liquid phase)`, `two-phase vapor-liquid (VL)`, `two-phase liquid-liquid (LL, aqueous+organic)` or `three-phase vapor-liquid-liquid (VLLE)`."],
      ["`V`, `L`", "number", "mole fraction", "Vapor fraction and total liquid fraction."],
      ["`n_phases`", "integer", "count", "Number of phases found."],
      ["`n_components_used`", "integer", "count", "Components that took part (mole fraction above 0)."],
      ["`vapor`, `aqueous`, `organic`", "object or null", "–", "One object per phase, null if the phase does not exist: `beta` (phase fraction of the total, mole fraction), `MW` (g/mol), `Cp` (J/mol/K), `rho_mass` (kg/m³), `rho_molar_kmol_m3` (kmol/m³)."],
      ["`mixture`", "object", "–", "`MW` (g/mol), `Cp` (J/mol/K), `Cp_mass_kJ_kgK` (kJ/kg/K), `rho_mass` (kg/m³), `rho_molar_kmol_m3` (kmol/m³)."]],
    notes: ["The phase with the most water is reported as **aqueous**, the other liquid as **organic**.", "The first request for a new set of components builds the model and can take a few seconds (about 3 s for 25 components); later requests for the same set take milliseconds.", WH_NOTE + " At this state the mixture is two liquids."],
    errors: ["validation_error", "unknown_component", "property_unavailable", "flash_failed", "calculation_timeout"],
  },
  {
    n: 12, group: "Enthalpy API", title: "Enthalpy and heat duty", method: "POST", path: "/eos_enthalpy_calc",
    purpose: "Enthalpy of one stream at an inlet and at an outlet condition, and the heat duty between them (outlet minus inlet), from a Peng-Robinson equation of state. A phase change between inlet and outlet, such as vaporisation, is included.",
    reqTable: [["`T_in`, `P_in`", "number", "Inlet temperature (K) and pressure (Pa), both above 0."],
      ["`T_out`, `P_out`", "number", "Outlet temperature (K) and pressure (Pa), both above 0."],
      ["`components`", "array of text", "Names or CAS numbers, no duplicates."],
      ["`zs`", "array of numbers", "Mole fractions or mole percent, same length and order. Rescaled to add up to 1."]],
    fields: [["`inlet`, `outlet`", "object", "–", "State at that condition: `vapor_fraction` (mole fraction), `molecular_weight` (g/mol), `enthalpy_molar` (kJ/mol), `enthalpy_mass` (kJ/kg)."],
      ["`duty.heat_duty_molar`", "number", "kJ/mol", "Outlet minus inlet enthalpy. Positive = heat absorbed, negative = heat released."],
      ["`duty.sp_duty`", "number", "kJ/kg", "Specific heat duty (per kilogram)."],
      ["`n_components_used`", "integer", "count", "Components that took part in the calculation."],
      ["`ethylene_ethane_kij_override`", "boolean", "–", "true when ethylene and ethane are both present and the calibrated interaction parameter 0.015 was used for that pair."]],
    notes: ["The example is a C2 stream (given in mole percent, so `meta.zs_normalized` is true) heated from 300 K to 368 K. Heating water from 300 K to 400 K at 101325 Pa gives a duty of 2717.545 kJ/kg, including the latent heat.",
      "Swapping inlet and outlet gives the same duty with the opposite sign.", "Components with a negligible mole fraction are skipped, so a long list with many zeros is fast. The first request for a new set of components builds the model (about 3 s)."],
    errors: ["validation_error", "unknown_component", "property_unavailable", "flash_failed", "calculation_timeout"],
    errSpecial: { flash_failed: "The equilibrium calculation did not work at the inlet or at the outlet condition; the message says which." },
  },
  {
    n: 13, group: "Vent API", title: "Flow versus valve opening", method: "POST", path: "/vent_flow_calc",
    purpose: "Fits a polynomial to your measured flow versus valve opening (equivalent to Excel LINEST with Flow as y and Opening as x) and estimates the flow at further openings. No components, temperature or pressure are involved.",
    reqTable: [["`opening_values`", "array of numbers", "Valve opening of each data point, in %. At least 3 points."],
      ["`flow_values`", "array of numbers", "Flow at each opening, in any one unit. Same length as `opening_values`."],
      ["`degree`", "integer", "Requested polynomial degree, 1 to 10. Reduced automatically to what the points support (points − 2)."],
      ["`estimate_at`", "array of numbers", "Openings (%) at which to estimate the flow. May be empty."],
      ["`clip_to_fit_range`", "boolean", "Default true: an opening outside the fitted range is evaluated at the nearest end of the range (still flagged as extrapolated)."],
      ["`min_flow`", "number", "Default 0. Floor applied to every estimated flow."]],
    fields: [["`fit.equation`", "string", "–", "The fitted equation as text."],
      ["`fit.terms`", "array", "–", "One entry per power, highest power first: `power`, `coefficient`, `standard_error`."],
      ["`fit.r_squared`, `fit.standard_error_y`, `fit.f_statistic`", "number or null", "–", "Fit statistics. null when undefined (all flows equal, or an exact fit)."],
      ["`fit.degree_requested`, `degree_used`, `degree_capped`", "integer, integer, boolean", "–", "The degree you asked for, the degree fitted, and whether it was reduced."],
      ["`fit.n_points`, `df_residual`, `ss_regression`, `ss_residual`", "number", "–", "Number of points, residual degrees of freedom, sums of squares."],
      ["`fit.opening_range`", "object", "%", "`min` and `max` opening the curve was fitted on."],
      ["`estimates[]`", "array", "–", "Per requested opening: `opening`, `opening_used`, `flow`, `extrapolated` (outside the fitted range), `floor_applied`."],
      ["`warnings[]`", "array of text", "–", "Plain-language notes, for example that the degree was reduced."]],
    notes: ["Flow, `standard_error_y` and the coefficients are in the unit of the flow values you send; nothing is converted. `meta` has only `request_id` and `elapsed_ms`.",
      "Use the lowest degree that describes the data. A high degree on few points follows the noise."],
    errors: ["validation_error", "fit_failed"],
    errExample: '{\n  "status": "error",\n  "error": {\n    "code": "fit_failed",\n    "message": "A degree-2 fit needs at least 3 different opening values; the data contain only 1.",\n    "details": { "distinct_opening_values": 1, "required": 3, "degree_used": 2 }\n  },\n  "request_id": "a1b2c3d4e5f6"\n}',
    errSpecial: { validation_error: "A list is shorter than 3 points, the two lists differ in length, the degree is outside 1 to 10, or a value is not a finite number." },
  },
];

// ----------------------------------------------------------------------------- build pages
const children = [];

// ---- cover
children.push(
  new Paragraph({ spacing: { before: 2600, after: 120 }, children: [new TextRun({ text: "THERMO PROPERTY API", font: FONT, size: 22, bold: true, color: BLUE, characterSpacing: 60 })] }),
  new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: "Integration Guide", font: FONT, size: 72, bold: true, color: NAVY })] }),
  new Paragraph({ spacing: { after: 600 }, border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: BLUE, space: 8 } },
    children: [new TextRun({ text: "How to call the API, with the request, response and errors of every endpoint", font: FONT, size: 28, color: GREY })] }),
  table(null, [
    ["Version", VERSION],
    ["Date", "23 October 2026"],
    ["Base URL", BASE],
    ["Interactive documentation", BASE + "/docs"],
    ["Format", "HTTP and JSON (UTF-8)"],
    ["Access", "Company network or VPN"],
    ["Authentication", "None in the current deployment"],
  ], [2800, 6838]),
  gap(300),
  new Paragraph({ spacing: { after: 100 }, children: [new TextRun({ text: "Contents", font: FONT, size: 26, bold: true, color: NAVY })] }),
  table(["Section", "Title", "Endpoint"], [
    ["1", "Overview", ""], ["2", "Request and response format", ""], ["3", "Errors", ""],
    ...apis.map((a) => [String(a.n), a.title, `${a.method} ${a.path}`]),
    ["14", "Health check", "GET /health"], ["15", "Client examples and version history", ""],
  ], [1100, 5200, 3338]),
);

// ---- 1 overview
children.push(...H1("1. Overview"));
children.push(P("The Thermo Property API calculates thermodynamic properties of mixtures. It has four groups. Every endpoint uses the same style of request and returns the same style of response, so once one works, the others follow."));
children.push(table(["Group", "Sections", "Use it when"], [
  ["**Property APIs**", "4 to 10", "You need one specific property (heat capacity, density, molecular weight, vapor fraction, or the vapor / aqueous / organic split). Vapor–liquid model, one endpoint per property."],
  ["**EOS Stream API**", "11", "You need the complete stream result in one call, or the phase behaviour matters (for example water with hydrocarbons). Peng-Robinson equation of state, three-phase flash."],
  ["**Enthalpy API**", "12", "You need the enthalpy of a stream at an inlet and an outlet condition and the heat duty between them."],
  ["**Vent API**", "13", "You have measured flow at several valve openings and need the flow at other openings. Works on your own data points."],
], [2200, 1100, 6338]));
children.push(H2("Endpoints"));
children.push(table(["Method and path", "Section", "Returns"], [
  ...apis.map((a) => [`${a.method} ${a.path}`, String(a.n), a.title]),
  ["GET /health", "14", "Service status and version"],
], [3400, 1000, 5238]));
children.push(H2("Rules that apply everywhere"));
children.push(...bullets([
  "All calculations use **POST** with a JSON body and the header `Content-Type: application/json`. `/health` uses GET.",
  "Temperature in **K**, pressure in **Pa**. Components are chemical names or CAS numbers. Mole fractions may also be given as mole percent; they are rescaled to add up to 1.",
  "A phase that does not exist at the given conditions is returned as **null**, never 0, and this is not an error.",
  "Values come back at full precision; round them in your own software. Unknown request fields are ignored.",
  "Every response has a `units` object that states the unit of each returned value, and a `request_id` for support.",
  "A calculation that takes longer than 30 seconds is stopped (error `calculation_timeout`).",
]));

// ---- 2 request and response format
children.push(...H1("2. Request and response format"));
children.push(H2("Common request (all calculations except sections 12 and 13)"));
children.push(table(["Field", "Type", "Rules"], [
  ["`T`", "number", "Temperature in K. Must be above 0."],
  ["`P`", "number", "Pressure in Pa. Must be above 0 (1 atm = 101325 Pa)."],
  ["`components`", "array of text", "Names or CAS numbers, for example `\"water\"` or `\"7732-18-5\"`. At least one, no duplicates, no limit on the number."],
  ["`zs`", "array of numbers", "Mole fractions in the same order and length as `components`. Not negative; the sum must be above 0. Rescaled to add up to 1; entries of 0 are allowed."],
], [1700, 1900, 6038]));
children.push(gap(80));
children.push(...code(DATA["/cp_calc"].request));
children.push(H2("Successful response (HTTP 200)"));
children.push(P("Every success has the same four parts. The example is the response of section 4.", { after: 80 }));
children.push(...code(DATA._envelope));
children.push(table(["Part", "Meaning"], [
  ["`status`", "Always `\"success\"`."],
  ["`data`", "The results; their fields are listed in each endpoint section."],
  ["`units`", "Unit of each value in `data`."],
  ["`meta`", "`request_id` (quote it when you contact support), `elapsed_ms` (server time) and, for calculations with a composition, `zs_normalized` (true if your fractions were rescaled)."],
], [1500, 8138]));
children.push(H2("Error response (HTTP 4xx or 5xx)"));
children.push(...code('{\n  "status": "error",\n  "error": {\n    "code": "validation_error",\n    "message": "Request body is invalid.",\n    "details": [ { "field": "T", "message": "Input should be greater than 0" } ]\n  },\n  "request_id": "a1b2c3d4e5f6"\n}'));
children.push(P("Use `error.code` in your software; it never changes. `message` is for people, and `details` carries the specifics (a list of fields for `validation_error`)."));

// ---- 3 errors
children.push(...H1("3. Errors"));
children.push(P("Always check the HTTP status first: 200 is success, anything else is an error in the format shown in section 2."));
children.push(table(["Error code", "HTTP", "Cause", "What to do"], [
  ["`validation_error`", "422", "The request is invalid: bad JSON, wrong type, T or P not above 0, lists of different length, negative fractions, duplicate or empty component, too few data points.", "Read `error.details` and fix the listed fields."],
  ["`unknown_component`", "422", "A name or CAS number is not known. `details.component` gives it.", "Use another spelling or the CAS number."],
  ["`flash_failed`", "422", "The equilibrium calculation failed for this state.", "Check temperature, pressure and composition."],
  ["`property_unavailable`", "422", "Data needed for a component is missing. `details.components` lists them.", "Remove or replace the component."],
  ["`water_required`", "422", "A triphase endpoint (sections 8 to 10) was called without water.", "Add water, or use the EOS Stream API."],
  ["`fit_failed`", "422", "Vent API only: too few different opening values for the degree.", "Provide more different openings or lower the degree."],
  ["`unauthorized`", "401", "An API key is enabled on the server and the `X-API-Key` header is missing or wrong.", "Send the correct key."],
  ["`not_found`", "404", "The URL does not exist.", "Check the path, including `/api`."],
  ["`method_not_allowed`", "405", "Wrong HTTP method, for example GET on a calculation.", "Use POST."],
  ["`calculation_failed`", "500", "The model could not be built.", "Report it with the `request_id`."],
  ["`internal_error`", "500", "Unexpected server error.", "Report it with the `request_id`."],
  ["`calculation_timeout`", "504", "The calculation took longer than 30 seconds.", "Simplify the input, or contact support."],
], [2100, 650, 4088, 2800]));
children.push(H2("Handling errors in your software"));
children.push(...bullets([
  "Decide by HTTP status and `error.code`, never by the text of `message`.",
  "Do not repeat a 422 request unchanged: the input has to change. A 504 may be repeated once with simpler input.",
  "Log the `request_id` of every failure; it lets support find the request in the server log.",
]));

// ---- API pages
for (const a of apis) {
  const d = DATA[a.path];
  children.push(...H1(`${a.n}. ${a.title}`, a.group));
  children.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: a.method, font: MONO, size: 22, bold: true, color: "FFFFFF", shading: { type: ShadingType.CLEAR, fill: BLUE, color: "auto" } }), new TextRun({ text: "  " + a.path, font: MONO, size: 22, bold: true, color: NAVY })] }));
  children.push(P(`${BASE}${a.path}`, { run: { size: 19, color: GREY }, after: 100 }));
  children.push(P(a.purpose));
  children.push(H2("Request"));
  if (a.reqTable) children.push(table(["Field", "Type", "Rules"], a.reqTable, [2100, 1700, 5838]), gap(80));
  else children.push(P(a.req, { after: 80 }));
  children.push(...code(d.request));
  const caption = a.exampleNote || (a.group === "Property APIs" ? WH_CAPTION : null) || (a.path === "/eos_stream_calc" ? WH_CAPTION_EOS : null);
  if (caption) children.push(P(caption, { run: { size: 18, color: GREY }, after: 60 }));
  children.push(H2("Response"));
  children.push(P("The example is the `data` part of the response; `units` and `meta` are as in section 2.", { after: 80, run: { size: 19, color: GREY } }));
  children.push(table(["Field", "Type", "Unit", "Description"], a.fields, [2500, 1500, 1200, 4438]));
  children.push(gap(80));
  children.push(...code(d.data));
  children.push(H2("Errors"));
  children.push(P(a.errors.map((c) => `\`${c}\` (${ERR[c][0]})`).join(", ") + ". Section 3 explains each code and what to do.", { after: 60 }));
  const specific = a.errors.filter((c) => (a.errSpecial && a.errSpecial[c]) || API_SPECIFIC_ERRORS.includes(c));
  if (specific.length) children.push(...bullets(specific.map((c) => `\`${c}\`: ${(a.errSpecial && a.errSpecial[c]) || ERR[c][1]}`)));
  if (a.errExample) children.push(...code(a.errExample));
  const notes = a.notes.filter((n) => !n.startsWith(WH_NOTE));
  if (notes.length) { children.push(H2("Notes")); children.push(...bullets(notes)); }
}

// ---- 14 health
children.push(...H1("14. Health check", "System"));
children.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "GET", font: MONO, size: 22, bold: true, color: "FFFFFF", shading: { type: ShadingType.CLEAR, fill: BLUE, color: "auto" } }), new TextRun({ text: "  /health", font: MONO, size: 22, bold: true, color: NAVY })] }));
children.push(P(`${BASE}/health`, { run: { size: 19, color: GREY }, after: 100 }));
children.push(P("Confirms that the service is running and tells you which version is deployed. It needs no body and no authentication, and is suitable for uptime monitoring."));
children.push(H2("Response"));
children.push(table(["Field", "Type", "Description"], [["`status`", "text", "`ok` while the service is alive."], ["`version`", "text", "The deployed API version."]], [2000, 1500, 6138]));
children.push(gap(80));
children.push(...code(DATA._health));
children.push(H2("Errors"));
children.push(P("None. If the service is down, the request fails at the network level or returns a 5xx from the web server."));

// ---- 15 examples and history
children.push(...H1("15. Client examples and version history"));
children.push(H2("Postman"));
children.push(...bullets([
  `Method **POST**, URL \`${BASE}/eos_stream_calc\` (or any other endpoint).`,
  "Body → **raw** → **JSON**, paste a request from the endpoint section, press **Send**. No API key is needed.",
]));
children.push(H2("curl (Windows Command Prompt)"));
children.push(...code(`curl.exe -X POST ${BASE}/vf_calc -H "Content-Type: application/json" ^\n  -d "{\\"T\\":300,\\"P\\":101325,\\"components\\":[\\"water\\",\\"hexane\\"],\\"zs\\":[0.5,0.5]}"`));
children.push(H2("Python"));
children.push(...code(`import requests

BASE = "${BASE}"
payload = {"T": 300, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5]}

resp = requests.post(f"{BASE}/eos_stream_calc", json=payload, timeout=60)
body = resp.json()
if resp.ok:                         # HTTP 200
    print(body["data"]["case"], body["data"]["mixture"]["Cp"])
else:                               # HTTP 4xx / 5xx
    err = body["error"]
    print(err["code"], err["message"], "request:", body["request_id"])`));
children.push(H2("Version history"));
children.push(table(["Version", "Change"], [
  ["2.3.0", "Added the Vent API (flow versus valve opening)."],
  ["2.2.0", "Added the Enthalpy API (enthalpy at inlet and outlet, heat duty)."],
  ["2.1.0", "Added the EOS Stream API. Documentation grouped by API."],
  ["2.0.0", "Consistent response format with units, proper HTTP status codes and error codes, strict validation, null for absent phases."],
], [1300, 8338]));

// ----------------------------------------------------------------------------- document
const footerText = (t) => new TextRun({ text: t, font: FONT, size: 16, color: GREY });
const doc = new Document({
  creator: "Thermo Property API", title: "Thermo Property API Integration Guide", description: `Version ${VERSION}`,
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 34, bold: true, font: FONT, color: NAVY }, paragraph: { spacing: { before: 0, after: 120 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 24, bold: true, font: FONT, color: BLUE }, paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  sections: [{
    properties: { titlePage: true, page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
    footers: {
      default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [footerText(`Thermo Property API · Integration Guide · version ${VERSION} · page `), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: GREY })] })] }),
      first: new Footer({ children: [new Paragraph({ children: [] })] }),
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log("written", OUT, buf.length, "bytes"); });
