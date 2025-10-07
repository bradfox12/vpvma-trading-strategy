import pandas as pd

print("="*80)
print("2022 BEAR MARKET: FILTERED vs FULL UNIVERSE COMPARISON")
print("Unbiased Analysis")
print("="*80)

# Load results
try:
    filtered = pd.read_csv('vpvma_2022_filtered_12_stocks.csv')
    full = pd.read_csv('vpvma_2022_full_54_universe.csv')
except FileNotFoundError as e:
    print(f"\n❌ Missing file: {e}")
    print("Run both 2022 backtest scripts first:")
    print("  1. python scripts/backtest_2022_filtered.py")
    print("  2. python scripts/backtest_2022_full_54.py")
    exit(1)

# Calculate stats
filtered_beat_bh = len(filtered[filtered['Alpha_%'] > 0])
full_beat_bh = len(full[full['Alpha_%'] > 0])

filtered_stats = {
    'count': len(filtered),
    'beat_bh_pct': (filtered_beat_bh / len(filtered)) * 100,
    'avg_return': filtered['Strategy_Return_%'].mean(),
    'median_return': filtered['Strategy_Return_%'].median(),
    'avg_alpha': filtered['Alpha_%'].mean(),
    'median_alpha': filtered['Alpha_%'].median(),
    'avg_dd': filtered['Strategy_MaxDD_%'].mean(),
    'avg_market_exp': filtered['Market_Exp_%'].mean()
}

full_stats = {
    'count': len(full),
    'beat_bh_pct': (full_beat_bh / len(full)) * 100,
    'avg_return': full['Strategy_Return_%'].mean(),
    'median_return': full['Strategy_Return_%'].median(),
    'avg_alpha': full['Alpha_%'].mean(),
    'median_alpha': full['Alpha_%'].median(),
    'avg_dd': full['Strategy_MaxDD_%'].mean(),
    'avg_market_exp': full['Market_Exp_%'].mean()
}

print(f"\n📊 UNIVERSE COMPARISON:")
print("="*80)
print(f"{'Metric':<35} {'Filtered (12)':<20} {'Full (54)':<20} {'Difference'}")
print("-" * 95)
print(f"{'Stocks Tested':<35} {filtered_stats['count']:<20} {full_stats['count']:<20} -")
print(f"{'Beat Buy & Hold %':<35} {filtered_stats['beat_bh_pct']:<20.1f} {full_stats['beat_bh_pct']:<20.1f} {filtered_stats['beat_bh_pct'] - full_stats['beat_bh_pct']:+.1f}%")
print(f"{'Avg Strategy Return %':<35} {filtered_stats['avg_return']:<20.2f} {full_stats['avg_return']:<20.2f} {filtered_stats['avg_return'] - full_stats['avg_return']:+.2f}%")
print(f"{'Median Strategy Return %':<35} {filtered_stats['median_return']:<20.2f} {full_stats['median_return']:<20.2f} {filtered_stats['median_return'] - full_stats['median_return']:+.2f}%")
print(f"{'Avg Alpha %':<35} {filtered_stats['avg_alpha']:<20.2f} {full_stats['avg_alpha']:<20.2f} {filtered_stats['avg_alpha'] - full_stats['avg_alpha']:+.2f}%")
print(f"{'Median Alpha %':<35} {filtered_stats['median_alpha']:<20.2f} {full_stats['median_alpha']:<20.2f} {filtered_stats['median_alpha'] - full_stats['median_alpha']:+.2f}%")
print(f"{'Avg Max Drawdown %':<35} {filtered_stats['avg_dd']:<20.2f} {full_stats['avg_dd']:<20.2f} {filtered_stats['avg_dd'] - full_stats['avg_dd']:+.2f}%")
print(f"{'Avg Market Exposure %':<35} {filtered_stats['avg_market_exp']:<20.1f} {full_stats['avg_market_exp']:<20.1f} {filtered_stats['avg_market_exp'] - full_stats['avg_market_exp']:+.1f}%")

# Verdict
print("\n" + "="*80)
print("VERDICT: DOES FILTERING HELP IN BEAR MARKETS?")
print("="*80)

score = 0
reasons = []

if filtered_stats['beat_bh_pct'] >= full_stats['beat_bh_pct']:
    print("✅ Similar or better beat-buy-hold rate")
    score += 1
    reasons.append("Beat B&H rate maintained or improved")
else:
    print("❌ Worse beat-buy-hold rate")
    reasons.append(f"Beat B&H rate dropped {filtered_stats['beat_bh_pct'] - full_stats['beat_bh_pct']:.1f}%")

if filtered_stats['avg_alpha'] >= full_stats['avg_alpha'] - 5:  # Within 5% tolerance
    print("✅ Similar or better average alpha")
    score += 1
    reasons.append("Alpha protection maintained")
else:
    print("❌ Significantly worse average alpha")
    reasons.append(f"Alpha dropped {filtered_stats['avg_alpha'] - full_stats['avg_alpha']:.1f}%")

if filtered_stats['median_alpha'] >= full_stats['median_alpha']:
    print("✅ Better or equal median alpha (more important)")
    score += 1
    reasons.append("Median alpha improved or maintained")
else:
    print("❌ Worse median alpha")
    reasons.append(f"Median alpha dropped {filtered_stats['median_alpha'] - full_stats['median_alpha']:.1f}%")

if filtered_stats['avg_dd'] >= full_stats['avg_dd'] - 10:  # Within 10% tolerance
    print("✅ Similar drawdown protection")
    score += 1
    reasons.append("Drawdowns within acceptable range")
else:
    print("❌ Significantly worse drawdowns")
    reasons.append(f"Drawdowns {filtered_stats['avg_dd'] - full_stats['avg_dd']:.1f}% worse")

print(f"\nBear Market Filtering Score: {score}/4")

print("\n" + "="*80)
if score >= 3:
    print("🎯 FILTERING MAINTAINS BEAR MARKET PROTECTION!")
    print("\n✅ Key Findings:")
    for reason in reasons:
        print(f"   • {reason}")
    print("\n📊 Conclusion:")
    print("   Pre-selecting trending stocks does not compromise bear market performance.")
    print("   The monthly universe selection strategy is FULLY VALIDATED.")
elif score == 2:
    print("⚠️  MIXED BEAR MARKET RESULTS")
    print("\n⚙️  Key Findings:")
    for reason in reasons:
        print(f"   • {reason}")
    print("\n📊 Conclusion:")
    print("   Filtering shows trade-offs in bear markets.")
    print("   Strategy still viable but with acknowledged higher volatility.")
else:
    print("❌ FILTERING HURTS BEAR MARKET PERFORMANCE")
    print("\n⚠️  Key Issues:")
    for reason in reasons:
        print(f"   • {reason}")
    print("\n📊 Conclusion:")
    print("   May need to adjust filtering criteria or add defensive positions.")

print("="*80)