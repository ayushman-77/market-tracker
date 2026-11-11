"""Curated multi-domain prediction market catalog (50 events across 5 domains).

Includes both binary YES/NO questions and Polymarket-style NegRisk multi-candidate
events (where each candidate has paired YES/NO CLOB outcome tokens).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateSeed:
    name: str
    yes_asset_id: str
    no_asset_id: str
    initial_yes_price: float


@dataclass(frozen=True)
class EventSeed:
    event_id: str
    condition_id: str
    slug: str
    category: str
    question: str
    oracle: str
    volume_24h: float
    open_interest: float
    is_multi_candidate: bool
    candidates: tuple[CandidateSeed, ...]


CATEGORIES: tuple[str, ...] = (
    "Crypto",
    "Politics",
    "Sports",
    "Geography",
    "Economy & Tech",
)


def _bin_event(
    event_id: str,
    slug: str,
    category: str,
    question: str,
    yes_price: float,
    volume_24h: float,
    open_interest: float,
    *,
    yes_asset_id: str | None = None,
    no_asset_id: str | None = None,
    condition_id: str | None = None,
) -> EventSeed:
    base = event_id.removeprefix("evt_")
    return EventSeed(
        event_id=event_id,
        condition_id=condition_id or f"c_{base}",
        slug=slug,
        category=category,
        question=question,
        oracle="UMA Optimistic Oracle v2",
        volume_24h=volume_24h,
        open_interest=open_interest,
        is_multi_candidate=False,
        candidates=(
            CandidateSeed(
                name="Outcome",
                yes_asset_id=yes_asset_id or f"tok_{base}_yes",
                no_asset_id=no_asset_id or f"tok_{base}_no",
                initial_yes_price=yes_price,
            ),
        ),
    )


def _multi_event(
    event_id: str,
    slug: str,
    category: str,
    question: str,
    volume_24h: float,
    open_interest: float,
    options: list[tuple[str, str, float]],
) -> EventSeed:
    base = event_id.removeprefix("evt_")
    candidates = tuple(
        CandidateSeed(
            name=name,
            yes_asset_id=f"tok_{base}_{key}_yes",
            no_asset_id=f"tok_{base}_{key}_no",
            initial_yes_price=price,
        )
        for key, name, price in options
    )
    return EventSeed(
        event_id=event_id,
        condition_id=f"c_{base}",
        slug=slug,
        category=category,
        question=question,
        oracle="UMA Optimistic Oracle v2",
        volume_24h=volume_24h,
        open_interest=open_interest,
        is_multi_candidate=True,
        candidates=candidates,
    )


# 50 curated events (10 per domain across Crypto, Politics, Sports, Geography, Economy & Tech).
# Keep tok_btc_100k_yes first so existing default market expectations remain unchanged.
EVENT_CATALOG: tuple[EventSeed, ...] = (
    # ===========================
    # 1. CRYPTO (10 Questions)
    # ===========================
    _bin_event(
        event_id="evt_btc_100k",
        slug="will-bitcoin-hit-100k-before-dec-31-2026",
        category="Crypto",
        question="Will Bitcoin hit $100k before Dec 31, 2026?",
        yes_price=0.520,
        volume_24h=4_280_500.0,
        open_interest=12_450_200.0,
        yes_asset_id="tok_btc_100k_yes",
        no_asset_id="tok_btc_100k_no",
        condition_id="c_btc_100k_eoy",
    ),
    _multi_event(
        event_id="evt_top_l1_eth_sol",
        slug="best-performing-major-layer-1-token-2026",
        category="Crypto",
        question="Which major Layer-1 token posts the highest 2026 return?",
        volume_24h=2_140_000.0,
        open_interest=6_820_000.0,
        options=[
            ("btc", "Bitcoin (BTC)", 0.310),
            ("sol", "Solana (SOL)", 0.290),
            ("eth", "Ethereum (ETH)", 0.220),
            ("sui", "Sui (SUI)", 0.110),
            ("other", "Other L1", 0.070),
        ],
    ),
    _multi_event(
        event_id="evt_eth_year_end_band",
        slug="ethereum-price-tier-end-of-2026",
        category="Crypto",
        question="Where will Ethereum (ETH) close at year-end 2026?",
        volume_24h=1_625_400.0,
        open_interest=4_910_000.0,
        options=[
            ("lt3k", "Below $3,000", 0.190),
            ("3k_4k", "$3,000 - $4,000", 0.340),
            ("4k_5k", "$4,000 - $5,500", 0.310),
            ("gt5500", "Above $5,500", 0.160),
        ],
    ),
    _multi_event(
        event_id="evt_stablecoin_leader_growth",
        slug="largest-stablecoin-net-inflow-q4-2026",
        category="Crypto",
        question="Which stablecoin records the largest net supply growth in Q4 2026?",
        volume_24h=890_300.0,
        open_interest=2_740_000.0,
        options=[
            ("usdt", "Tether (USDT)", 0.440),
            ("usdc", "USD Coin (USDC)", 0.390),
            ("usde", "Ethena (USDe)", 0.110),
            ("other", "Other Stablecoin", 0.060),
        ],
    ),
    _bin_event(
        event_id="evt_sol_etf_us",
        slug="spot-solana-etf-approved-in-us-2026",
        category="Crypto",
        question="Will a US Spot Solana ETF receive SEC approval in 2026?",
        yes_price=0.640,
        volume_24h=1_980_200.0,
        open_interest=5_340_800.0,
    ),
    _bin_event(
        event_id="evt_btc_dominance_60",
        slug="bitcoin-dominance-above-60-percent-q4",
        category="Crypto",
        question="Will Bitcoin market dominance stay above 60% through Q4?",
        yes_price=0.470,
        volume_24h=740_900.0,
        open_interest=1_950_400.0,
    ),
    _bin_event(
        event_id="evt_eth_pectra_blob_2x",
        slug="ethereum-l2-daily-blobs-exceed-150k",
        category="Crypto",
        question="Will Ethereum L2 rollup daily blob usage exceed 150k this year?",
        yes_price=0.580,
        volume_24h=512_600.0,
        open_interest=1_410_000.0,
    ),
    _bin_event(
        event_id="evt_defi_tvl_150b",
        slug="total-defi-tvl-surpasses-150b-2026",
        category="Crypto",
        question="Will aggregate DeFi TVL surpass $150B before Dec 31, 2026?",
        yes_price=0.410,
        volume_24h=625_100.0,
        open_interest=1_780_500.0,
    ),
    _bin_event(
        event_id="evt_us_strategic_btc",
        slug="us-treasury-adds-bitcoin-reserve-2026",
        category="Crypto",
        question="Will the US Treasury formally hold Bitcoin as a reserve asset in 2026?",
        yes_price=0.280,
        volume_24h=2_340_000.0,
        open_interest=7_120_300.0,
    ),
    _bin_event(
        event_id="evt_polymarket_vol_record",
        slug="polymarket-monthly-volume-exceeds-5b",
        category="Crypto",
        question="Will Polymarket monthly trading volume exceed $5B in any month of 2026?",
        yes_price=0.710,
        volume_24h=1_120_800.0,
        open_interest=3_090_100.0,
    ),
    # ===========================
    # 2. POLITICS (10 Questions)
    # ===========================
    _multi_event(
        event_id="evt_us_pres_2028",
        slug="who-will-win-the-2028-us-presidential-election",
        category="Politics",
        question="Who will win the 2028 US Presidential Election?",
        volume_24h=5_840_900.0,
        open_interest=18_250_400.0,
        options=[
            ("vance", "JD Vance", 0.340),
            ("newsom", "Gavin Newsom", 0.250),
            ("ossoff", "Jon Ossoff", 0.170),
            ("aoc", "Alexandria Ocasio-Cortez", 0.120),
            ("other", "Other Candidate", 0.120),
        ],
    ),
    _multi_event(
        event_id="evt_dem_nominee_2028",
        slug="democratic-nominee-2028-presidential-race",
        category="Politics",
        question="Who will win the 2028 Democratic Presidential Nomination?",
        volume_24h=2_910_400.0,
        open_interest=8_410_200.0,
        options=[
            ("newsom", "Gavin Newsom", 0.320),
            ("shapiro", "Josh Shapiro", 0.230),
            ("ossoff", "Jon Ossoff", 0.190),
            ("whitmer", "Gretchen Whitmer", 0.140),
            ("other", "Other Nominee", 0.120),
        ],
    ),
    _multi_event(
        event_id="evt_gop_nominee_2028",
        slug="republican-nominee-2028-presidential-race",
        category="Politics",
        question="Who will win the 2028 Republican Presidential Nomination?",
        volume_24h=2_680_100.0,
        open_interest=7_950_000.0,
        options=[
            ("vance", "JD Vance", 0.560),
            ("desantis", "Ron DeSantis", 0.160),
            ("haley", "Nikki Haley", 0.130),
            ("rubio", "Marco Rubio", 0.090),
            ("other", "Other Nominee", 0.060),
        ],
    ),
    _multi_event(
        event_id="evt_france_pres_2027",
        slug="next-president-of-france-2027",
        category="Politics",
        question="Who will win the 2027 French Presidential Election?",
        volume_24h=1_430_600.0,
        open_interest=4_210_900.0,
        options=[
            ("bardella", "Jordan Bardella", 0.380),
            ("philippe", "Edouard Philippe", 0.270),
            ("melenchon", "Jean-Luc Melenchon", 0.140),
            ("other", "Other Candidate", 0.210),
        ],
    ),
    _bin_event(
        event_id="evt_us_senate_2026",
        slug="republicans-hold-us-senate-majority-2026",
        category="Politics",
        question="Will Republicans retain US Senate control after the 2026 midterms?",
        yes_price=0.620,
        volume_24h=1_890_000.0,
        open_interest=6_120_000.0,
    ),
    _bin_event(
        event_id="evt_us_house_2026",
        slug="democrats-win-us-house-majority-2026",
        category="Politics",
        question="Will Democrats win majority control of the US House in 2026?",
        yes_price=0.550,
        volume_24h=1_740_300.0,
        open_interest=5_430_000.0,
    ),
    _bin_event(
        event_id="evt_uk_pm_stability",
        slug="keir-starmer-remains-uk-pm-end-2026",
        category="Politics",
        question="Will Keir Starmer remain UK Prime Minister through Dec 31, 2026?",
        yes_price=0.730,
        volume_24h=815_400.0,
        open_interest=2_680_000.0,
    ),
    _bin_event(
        event_id="evt_un_security_reform",
        slug="un-passes-ai-governance-treaty-2026",
        category="Politics",
        question="Will the UN General Assembly adopt a binding AI treaty in 2026?",
        yes_price=0.210,
        volume_24h=410_200.0,
        open_interest=1_150_000.0,
    ),
    _bin_event(
        event_id="evt_india_one_nation_bill",
        slug="india-passes-simultaneous-elections-bill-2026",
        category="Politics",
        question="Will India pass the One Nation One Election bill in 2026?",
        yes_price=0.370,
        volume_24h=690_500.0,
        open_interest=2_140_000.0,
    ),
    _bin_event(
        event_id="evt_canada_snap_election",
        slug="canada-holds-federal-vote-before-mid-2027",
        category="Politics",
        question="Will Canada hold an early federal election before June 2027?",
        yes_price=0.480,
        volume_24h=530_800.0,
        open_interest=1_620_000.0,
    ),
    # ===========================
    # 3. SPORTS (10 Questions)
    # ===========================
    _multi_event(
        event_id="evt_ucl_2027_winner",
        slug="2026-27-uefa-champions-league-winner",
        category="Sports",
        question="Who will win the 2026-27 UEFA Champions League?",
        volume_24h=3_120_400.0,
        open_interest=9_340_000.0,
        options=[
            ("real_madrid", "Real Madrid", 0.260),
            ("man_city", "Manchester City", 0.220),
            ("arsenal", "Arsenal", 0.170),
            ("barcelona", "FC Barcelona", 0.160),
            ("other", "Other Club", 0.190),
        ],
    ),
    _multi_event(
        event_id="evt_nba_2027_champ",
        slug="2027-nba-championship-winner",
        category="Sports",
        question="Which team will win the 2027 NBA Championship?",
        volume_24h=2_450_000.0,
        open_interest=7_120_000.0,
        options=[
            ("okc", "Oklahoma City Thunder", 0.280),
            ("celtics", "Boston Celtics", 0.230),
            ("nuggets", "Denver Nuggets", 0.160),
            ("knicks", "New York Knicks", 0.140),
            ("other", "Other Team", 0.190),
        ],
    ),
    _multi_event(
        event_id="evt_f1_2026_constructors",
        slug="2026-formula-1-constructors-champion",
        category="Sports",
        question="Which team wins the 2026 Formula 1 Constructors' Championship?",
        volume_24h=1_540_800.0,
        open_interest=4_480_000.0,
        options=[
            ("ferrari", "Ferrari", 0.310),
            ("mclaren", "McLaren", 0.290),
            ("mercedes", "Mercedes", 0.200),
            ("red_bull", "Red Bull Racing", 0.140),
            ("other", "Other Team", 0.060),
        ],
    ),
    _multi_event(
        event_id="evt_ipl_2027_winner",
        slug="ipl-2027-championship-winner",
        category="Sports",
        question="Which franchise will win the 2027 IPL Championship?",
        volume_24h=1_890_200.0,
        open_interest=5_620_000.0,
        options=[
            ("mi", "Mumbai Indians", 0.240),
            ("rcb", "Royal Challengers Bengaluru", 0.220),
            ("csk", "Chennai Super Kings", 0.180),
            ("srh", "Sunrisers Hyderabad", 0.160),
            ("other", "Other Franchise", 0.200),
        ],
    ),
    _bin_event(
        event_id="evt_ipl_200m_auction",
        slug="virat-kohli-scores-over-600-runs-next-ipl",
        category="Sports",
        question="Will Virat Kohli finish in the top 5 run-scorers in the next IPL season?",
        yes_price=0.590,
        volume_24h=780_400.0,
        open_interest=2_150_000.0,
    ),
    _bin_event(
        event_id="evt_djokovic_25th_slam",
        slug="novak-djokovic-wins-25th-grand-slam-before-2027",
        category="Sports",
        question="Will Novak Djokovic win a 25th Grand Slam singles title?",
        yes_price=0.310,
        volume_24h=940_100.0,
        open_interest=2_890_000.0,
    ),
    _bin_event(
        event_id="evt_epl_title_points",
        slug="epl-2026-27-champion-exceeds-90-points",
        category="Sports",
        question="Will the 2026-27 Premier League champion finish with over 90 points?",
        yes_price=0.440,
        volume_24h=620_000.0,
        open_interest=1_730_000.0,
    ),
    _bin_event(
        event_id="evt_ohtani_50_50_again",
        slug="shohei-ohtani-repeats-40-40-mlb-season",
        category="Sports",
        question="Will Shohei Ohtani log another 40-40 MLB regular season?",
        yes_price=0.360,
        volume_24h=850_700.0,
        open_interest=2_410_000.0,
    ),
    _bin_event(
        event_id="evt_nfl_18_game_season",
        slug="nfl-approves-18-game-regular-season-2027",
        category="Sports",
        question="Will NFL owners formally approve an 18-game season by mid-2027?",
        yes_price=0.420,
        volume_24h=710_300.0,
        open_interest=1_980_000.0,
    ),
    _bin_event(
        event_id="evt_india_wtc_final_2027",
        slug="india-qualifies-2027-wtc-final-lords",
        category="Sports",
        question="Will India qualify for the 2027 ICC World Test Championship Final?",
        yes_price=0.670,
        volume_24h=1_050_900.0,
        open_interest=3_180_000.0,
    ),
    # ===========================
    # 4. GEOGRAPHY (10 Questions)
    # ===========================
    _multi_event(
        event_id="evt_hottest_year_rank",
        slug="global-surface-temp-anomaly-2026-ranking",
        category="Geography",
        question="Where will 2026 rank in global surface temperature anomaly records?",
        volume_24h=840_500.0,
        open_interest=2_340_000.0,
        options=[
            ("rank1", "Warmest on Record (#1)", 0.290),
            ("top3", "Top 3 Warmest (#2-#3)", 0.460),
            ("top5", "Top 5 (#4-#5)", 0.190),
            ("outside", "Outside Top 5", 0.060),
        ],
    ),
    _multi_event(
        event_id="evt_enso_phase_winter",
        slug="enso-pacific-climate-phase-djf-2026-27",
        category="Geography",
        question="Which ENSO climate phase prevails in the Equatorial Pacific this winter?",
        volume_24h=610_200.0,
        open_interest=1_890_000.0,
        options=[
            ("el_nino", "El Nino", 0.430),
            ("neutral", "ENSO Neutral", 0.410),
            ("la_nina", "La Nina", 0.160),
        ],
    ),
    _multi_event(
        event_id="evt_fastest_growing_megacity",
        slug="region-with-highest-urban-population-growth-2026",
        category="Geography",
        question="Which region leads global megacity urban population growth in 2026-27?",
        volume_24h=390_400.0,
        open_interest=1_120_000.0,
        options=[
            ("south_asia", "South Asia", 0.370),
            ("sub_sahara", "Sub-Saharan Africa", 0.350),
            ("se_asia", "Southeast Asia", 0.190),
            ("latam", "Latin America", 0.090),
        ],
    ),
    _multi_event(
        event_id="evt_shipping_chokepoint_delay",
        slug="busiest-maritime-strait-by-rerouted-tonnage-2026",
        category="Geography",
        question="Which maritime strait experiences the highest rerouting disruption in 2026?",
        volume_24h=975_600.0,
        open_interest=2_910_000.0,
        options=[
            ("bab_el_mandeb", "Bab el-Mandeb (Red Sea)", 0.480),
            ("hormuz", "Strait of Hormuz", 0.240),
            ("panama", "Panama Canal Locks", 0.170),
            ("malacca", "Strait of Malacca", 0.110),
        ],
    ),
    _bin_event(
        event_id="evt_arctic_sea_ice_record",
        slug="arctic-september-sea-ice-extent-below-4m-sqkm",
        category="Geography",
        question="Will Arctic summer sea-ice extent fall below 4.0M sq km next season?",
        yes_price=0.380,
        volume_24h=520_000.0,
        open_interest=1_480_000.0,
    ),
    _bin_event(
        event_id="evt_nile_grand_renaissance",
        slug="nile-basin-water-sharing-accord-signed-2026",
        category="Geography",
        question="Will Egypt, Sudan, and Ethiopia sign a binding Nile dam water accord?",
        yes_price=0.220,
        volume_24h=345_100.0,
        open_interest=980_000.0,
    ),
    _bin_event(
        event_id="evt_iceland_reykjanes_eruption",
        slug="reykjanes-peninsula-volcanic-eruption-winter",
        category="Geography",
        question="Will Iceland's Reykjanes Peninsula record a new volcanic fissure eruption this quarter?",
        yes_price=0.610,
        volume_24h=470_800.0,
        open_interest=1_310_000.0,
    ),
    _bin_event(
        event_id="evt_amazon_deforestation_drop",
        slug="brazil-amazon-deforestation-falls-20-percent",
        category="Geography",
        question="Will annual Brazilian Amazon deforestation decline by over 20% YoY?",
        yes_price=0.540,
        volume_24h=410_300.0,
        open_interest=1_190_000.0,
    ),
    _bin_event(
        event_id="evt_atlantic_cat5_hurricane",
        slug="atlantic-basin-records-category-5-hurricane-2027",
        category="Geography",
        question="Will the Atlantic hurricane basin record at least one Category 5 storm next season?",
        yes_price=0.560,
        volume_24h=665_900.0,
        open_interest=1_870_000.0,
    ),
    _bin_event(
        event_id="evt_northern_sea_route_cargo",
        slug="northern-sea-route-transit-cargo-tops-40m-tons",
        category="Geography",
        question="Will Arctic Northern Sea Route transit cargo exceed 40M metric tons this year?",
        yes_price=0.450,
        volume_24h=315_400.0,
        open_interest=890_000.0,
    ),
    # ===========================
    # 5. ECONOMY & TECH (10 Questions)
    # ===========================
    _bin_event(
        event_id="evt_fed_cut_q1",
        slug="will-federal-reserve-cut-rates-in-q1",
        category="Economy & Tech",
        question="Will Federal Reserve cut rates in Q1?",
        yes_price=0.460,
        volume_24h=3_420_100.0,
        open_interest=9_810_000.0,
        yes_asset_id="tok_fed_cut_yes",
        no_asset_id="tok_fed_cut_no",
        condition_id="c_fed_cut_q1",
    ),
    _multi_event(
        event_id="evt_ai_arena_leader_eoy",
        slug="top-ai-lab-chatbot-arena-elo-end-2026",
        category="Economy & Tech",
        question="Which AI lab holds #1 Chatbot Arena Elo at year-end?",
        volume_24h=2_790_500.0,
        open_interest=8_120_000.0,
        options=[
            ("google", "Google DeepMind", 0.340),
            ("anthropic", "Anthropic", 0.310),
            ("openai", "OpenAI", 0.250),
            ("xai", "xAI", 0.060),
            ("other", "Other Lab", 0.040),
        ],
    ),
    _multi_event(
        event_id="evt_fed_funds_target_range",
        slug="us-federal-funds-rate-range-dec-2026",
        category="Economy & Tech",
        question="What will the US Federal Funds target upper bound be after the Dec meeting?",
        volume_24h=3_180_000.0,
        open_interest=10_450_000.0,
        options=[
            ("350", "3.50% or Lower", 0.280),
            ("375", "3.75%", 0.370),
            ("400", "4.00%", 0.240),
            ("425", "4.25% or Higher", 0.110),
        ],
    ),
    _multi_event(
        event_id="evt_first_5t_company",
        slug="first-company-to-reach-5-trillion-market-cap",
        category="Economy & Tech",
        question="Which company reaches a $5 Trillion market capitalization first?",
        volume_24h=2_110_800.0,
        open_interest=6_420_000.0,
        options=[
            ("nvda", "NVIDIA", 0.440),
            ("aapl", "Apple", 0.260),
            ("msft", "Microsoft", 0.190),
            ("googl", "Alphabet", 0.080),
            ("other", "Other Company", 0.030),
        ],
    ),
    _bin_event(
        event_id="evt_us_cpi_below_2_5",
        slug="us-annual-cpi-prints-below-2-5-percent",
        category="Economy & Tech",
        question="Will US headline CPI YoY print below 2.5% in any upcoming reading?",
        yes_price=0.510,
        volume_24h=1_640_200.0,
        open_interest=4_720_000.0,
    ),
    _bin_event(
        event_id="evt_sp500_above_6800",
        slug="sp-500-closes-year-above-6800",
        category="Economy & Tech",
        question="Will the S&P 500 close the calendar year above 6,800?",
        yes_price=0.570,
        volume_24h=1_920_000.0,
        open_interest=5_840_000.0,
    ),
    _bin_event(
        event_id="evt_spacex_starship_catch_v3",
        slug="spacex-catches-starship-ship-and-booster",
        category="Economy & Tech",
        question="Will SpaceX successfully catch both Starship Super Heavy booster and upper stage?",
        yes_price=0.690,
        volume_24h=1_380_400.0,
        open_interest=3_950_000.0,
    ),
    _bin_event(
        event_id="evt_tsmc_2nm_apple_ship",
        slug="apple-ships-tsmc-2nm-consumer-silicon",
        category="Economy & Tech",
        question="Will Apple ship mass-produced consumer devices using TSMC 2nm silicon this cycle?",
        yes_price=0.760,
        volume_24h=870_300.0,
        open_interest=2_410_000.0,
    ),
    _bin_event(
        event_id="evt_us_recession_2026",
        slug="nber-declares-us-recession-before-2027",
        category="Economy & Tech",
        question="Will the NBER declare a US recession starting before mid-2027?",
        yes_price=0.230,
        volume_24h=2_040_000.0,
        open_interest=6_310_000.0,
    ),
    _bin_event(
        event_id="evt_waymo_1m_weekly_rides",
        slug="waymo-surpasses-1-million-paid-weekly-rides",
        category="Economy & Tech",
        question="Will Waymo surpass 1 million paid autonomous rides per week?",
        yes_price=0.620,
        volume_24h=945_700.0,
        open_interest=2_780_000.0,
    ),
)

