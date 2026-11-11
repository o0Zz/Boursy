"""Initial healthcare universe (PEA-eligible EU/EEA companies), using Yahoo Finance symbols.

Buckets: "core" = large, established companies; "growth" = small/mid caps and biotech exposed to
binary events (trial readouts, regulator decisions). Buckets are defaults and editable in the dashboard.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from boursy.db.models import Stock

# EU member states + EEA (Iceland, Liechtenstein, Norway): companies headquartered there are PEA-eligible.
PEA_COUNTRIES = frozenset(
    "AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK IS LI NO".split()
)

# Yahoo symbol suffix -> (ISO 10383 exchange MIC, currency)
SUFFIX_EXCHANGE = {
    "PA": ("XPAR", "EUR"),
    "AS": ("XAMS", "EUR"),
    "BR": ("XBRU", "EUR"),
    "LS": ("XLIS", "EUR"),
    "MI": ("XMIL", "EUR"),
    "MC": ("XMAD", "EUR"),
    "DE": ("XETR", "EUR"),
    "CO": ("XCSE", "DKK"),
    "ST": ("XSTO", "SEK"),
    "HE": ("XHEL", "EUR"),
}


@dataclass(frozen=True)
class SeedStock:
    symbol: str
    name: str
    country: str
    bucket: str


SEED: tuple[SeedStock, ...] = (
    # core
    SeedStock("SAN.PA", "Sanofi", "FR", "core"),
    SeedStock("EL.PA", "EssilorLuxottica", "FR", "core"),
    SeedStock("BIM.PA", "bioMérieux", "FR", "core"),
    SeedStock("DIM.PA", "Sartorius Stedim Biotech", "FR", "core"),
    SeedStock("IPN.PA", "Ipsen", "FR", "core"),
    SeedStock("ERF.PA", "Eurofins Scientific", "LU", "core"),
    SeedStock("NOVO-B.CO", "Novo Nordisk", "DK", "core"),
    SeedStock("COLO-B.CO", "Coloplast", "DK", "core"),
    SeedStock("GMAB.CO", "Genmab", "DK", "core"),
    SeedStock("SHL.DE", "Siemens Healthineers", "DE", "core"),
    SeedStock("MRK.DE", "Merck KGaA", "DE", "core"),
    SeedStock("FRE.DE", "Fresenius", "DE", "core"),
    SeedStock("PHIA.AS", "Philips", "NL", "core"),
    SeedStock("UCB.BR", "UCB", "BE", "core"),
    SeedStock("ARGX.BR", "argenx", "NL", "core"),
    SeedStock("REC.MI", "Recordati", "IT", "core"),
    SeedStock("GRF.MC", "Grifols", "ES", "core"),
    # growth
    SeedStock("MEDCL.PA", "Medincell", "FR", "growth"),
    SeedStock("VLA.PA", "Valneva", "FR", "growth"),
    SeedStock("NANO.PA", "Nanobiotix", "FR", "growth"),
    SeedStock("ABVX.PA", "Abivax", "FR", "growth"),
    SeedStock("VIRP.PA", "Virbac", "FR", "growth"),
    SeedStock("VETO.PA", "Vetoquinol", "FR", "growth"),
    SeedStock("GBT.PA", "Guerbet", "FR", "growth"),
    SeedStock("DIA.MI", "DiaSorin", "IT", "growth"),
    SeedStock("AMP.MI", "Amplifon", "IT", "growth"),
)


def exchange_for(symbol: str) -> tuple[str, str]:
    suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
    if suffix not in SUFFIX_EXCHANGE:
        raise ValueError(
            f"Unsupported exchange suffix for {symbol!r}; expected one of {sorted(SUFFIX_EXCHANGE)}"
        )
    return SUFFIX_EXCHANGE[suffix]


def make_stock(symbol: str, name: str, country: str, bucket: str) -> Stock:
    if bucket not in ("core", "growth"):
        raise ValueError("bucket must be 'core' or 'growth'")
    exchange, currency = exchange_for(symbol)
    country = country.upper()
    return Stock(
        symbol=symbol.upper(),
        name=name,
        country=country,
        exchange=exchange,
        currency=currency,
        bucket=bucket,
        pea_eligible=country in PEA_COUNTRIES,
        active=True,
    )


def seed_universe(session: Session) -> int:
    """Insert the seed list when the stock table is empty. Returns the number of stocks added."""
    if session.scalar(select(func.count(Stock.id))):
        return 0
    for s in SEED:
        session.add(make_stock(s.symbol, s.name, s.country, s.bucket))
    session.commit()
    return len(SEED)
