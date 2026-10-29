"""Generate typeset/allowlist.txt: the control words a formula may use.

Run from the repo root (host Python, stdlib only):
    python3 typeset/gen_allowlist.py frontend/node_modules/katex/dist/katex.mjs \
        frontend/src/components/math/macros.ts > typeset/allowlist.txt

Sources:
- every "\\name" string literal in KaTeX's dist/katex.mjs (its functions,
  symbols and built-in macros), katex@0.16.21;
- the KaTeX macro names (and siunitx unit/prefix names) in macros.ts;
- the curated package lists below (mhchem, chemfig, siunitx, physics,
  braket, cancel);
minus EXCLUDE (anything that defines macros, builds control-sequence names,
changes catcodes, groups/expansion tricks, or touches files/URLs/specials).
"""

from __future__ import annotations

import re
import sys

MHCHEM = "ce pu cee cf bond"
CHEMFIG = (
    "chemfig chemname chemabove chembelow chemleft chemright chemup chemdown lewis Lewis "
    "chemsign chemrel chemmove schemestart schemestop arrow subscheme charge Charge "
    "chemskipalign polymerdelim chemnameinit"
)
SIUNITX = (
    "SI si qty unit num ang SIrange numrange qtyrange SIlist numlist qtylist unitlist "
    "complexnum complexqty numproduct qtyproduct "
    # units
    "metre meter gram kilogram second ampere kelvin mole candela becquerel degreeCelsius "
    "coulomb farad gray hertz henry joule katal lumen lux newton ohm pascal radian siemens "
    "sievert steradian tesla volt watt weber astronomicalunit bel dalton day decibel degree "
    "electronvolt hectare hour litre liter arcminute arcsecond minute neper tonne percent "
    "angstrom bar barn knot mmHg nauticalmile atomicmassunit "
    # prefixes
    "quecto ronto yocto zepto atto femto pico nano micro milli centi deci deca deka hecto "
    "kilo mega giga tera peta exa zetta yotta ronna quetta "
    # powers and joins
    "per square cubic squared cubed tothe raiseto of "
    # abbreviations
    "fg pg ng ug mg g kg amu pm nm um mm cm dm m km as fs ps ns us ms s fmol pmol nmol umol "
    "mmol mol kmol pA nA uA mA A kA ul ml l hl uL mL L hL mHz Hz kHz MHz GHz THz mN N kN MN "
    "Pa kPa MPa GPa mohm kohm Mohm pV nV uV mV V kV W nW uW mW kW MW GW J uJ mJ kJ eV meV keV "
    "MeV GeV TeV kWh F fF pF nF uF H mH C nC mC uC K dB T mT"
)
PHYSICS = (
    "qty abs norm order comm acomm pb poissonbracket commutator anticommutator vb "
    "vectorbold va vectorarrow vu vectorunit dotproduct vdot crossproduct cross cp "
    "gradient grad divergence curl laplacian tr trace Tr rank erf Res pv PV Re Im "
    "asin acos atan asec acsc acot asinh acosh atanh sech csch "
    "dd dv derivative pdv partialderivative var variation fdv functionalderivative "
    "bra ket braket innerproduct ip ketbra outerproduct dyad op expval expectationvalue ev "
    "matrixel matrixelement mel mqty pmqty Pmqty bmqty vmqty smqty spmqty sPmqty sbmqty "
    "svmqty matrixquantity smallmatrixquantity imat identitymatrix xmat xmatrix zmat "
    "zeromatrix paulimat paulimatrix dmat diagonalmatrix admat antidiagonalmatrix "
    "qq qc qcomma qcc qand qor qif qthen qelse qotherwise qunless qgiven qusing qassume "
    "qsince qlet qfor qall qeven qodd qinteger qsum qdifference qproduct qquotient "
    "qcomplement qisotherwise eval evaluated pqty bqty Bqty vqty quantity "
    "Bra Ket Braket Set set"
)
CANCEL = "cancel bcancel xcancel cancelto"

EXCLUDE = set(
    """
    input include includeonly endinput openin closein openout closeout read readline write
    immediate message errmessage special shipout filedump filesize filemoddate mdfivesum
    pdffilesize pdfmdfivesum pdffiledump IfFileExists InputIfFileExists UseName use
    csname endcsname expandafter noexpand unexpanded def gdef edef xdef let futurelet global
    long outer protected afterassignment aftergroup newcommand renewcommand providecommand
    DeclareRobustCommand NewDocumentCommand RenewDocumentCommand newenvironment
    renewenvironment catcode lccode uccode mathcode delcode sfcode scantokens string
    detokenize meaning number romannumeral lowercase uppercase begingroup endgroup bgroup
    egroup usepackage RequirePackage documentclass makeatletter makeatother ExplSyntaxOn
    ExplSyntaxOff VerbatimInput lstinputlisting verbatiminput directlua luaexec
    includegraphics href url htmlClass htmlId htmlStyle htmlData TextOrMath relax
    batchmode nonstopmode scrollmode errorstopmode jobname verb char
    setchemfig definesubmol definesubmolecule sisetup
    """.split()
)


def main(katex_mjs: str, macros_ts: str) -> None:
    katex = open(katex_mjs, encoding="utf-8").read()
    names = set(re.findall(r"[\"']\\\\([A-Za-z]+)[\"']", katex))
    ts = open(macros_ts, encoding="utf-8").read()
    names |= set(re.findall(r"\"\\\\([A-Za-z]+)\"\s*[:\]]", ts))
    for block in re.findall(r"const (?:UNITS|PREFIXES|POWERS)[^{]*\{(.*?)\};", ts, re.S):
        names |= set(re.findall(r"(\w+)\s*:", block))
    names |= {"per", "squared", "cubed"}
    for group in (MHCHEM, CHEMFIG, SIUNITX, PHYSICS, CANCEL):
        names |= set(group.split())
    names -= EXCLUDE
    print("# Control words a formula may use (one per line, without the backslash).")
    print("# Generated by typeset/gen_allowlist.py from katex@0.16.21 dist/katex.mjs,")
    print("# frontend/src/components/math/macros.ts and curated mhchem/chemfig/siunitx/")
    print("# physics/braket/cancel lists, minus the file/definition/expansion EXCLUDE set.")
    for n in sorted(names):
        print(n)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
