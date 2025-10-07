"""
Visualization utilities for performance dashboard
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

def create_equity_curve_chart(equity_data, title="Equity Curve"):
    """
    Create interactive equity curve with comparison to buy-and-hold
    """
    fig = go.Figure()
    
    # Strategy equity curve
    fig.add_trace(go.Scatter(
        x=equity_data['dates'],
        y=equity_data['strategy_equity'],
        mode='lines',
        name='VPVMA Strategy',
        line=dict(color='#2E86AB', width=2),
        hovertemplate='Date: %{x}<br>Equity: $%{y:,.0f}<extra></extra>'
    ))
    
    # Buy and hold comparison
    if 'bh_equity' in equity_data:
        fig.add_trace(go.Scatter(
            x=equity_data['dates'],
            y=equity_data['bh_equity'],
            mode='lines',
            name='Buy & Hold',
            line=dict(color='#A23B72', width=2, dash='dash'),
            hovertemplate='Date: %{x}<br>Equity: $%{y:,.0f}<extra></extra>'
        ))
    
    fig.update_layout(
        title=title,
        xaxis_title='Date',
        yaxis_title='Equity ($)',
        hovermode='x unified',
        template='plotly_white',
        height=400,
        showlegend=True,
        legend=dict(x=0.01, y=0.99)
    )
    
    return fig.to_html(include_plotlyjs='cdn', div_id=f'equity_{title.replace(" ", "_")}')

def create_drawdown_chart(equity_curve):
    """
    Create drawdown chart showing underwater periods
    """
    if len(equity_curve) == 0:
        return "<div style='padding: 20px; background: #f8f9fa; text-align: center;'>No drawdown data available</div>"
    
    equity_array = np.array(equity_curve)
    running_max = np.maximum.accumulate(equity_array)
    drawdown = (equity_array - running_max) / running_max * 100
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=list(range(len(drawdown))),
        y=drawdown,
        fill='tozeroy',
        fillcolor='rgba(231, 76, 60, 0.3)',
        line=dict(color='#E74C3C', width=2),
        name='Drawdown',
        hovertemplate='Day: %{x}<br>Drawdown: %{y:.1f}%<extra></extra>'
    ))
    
    fig.update_layout(
        title='Drawdown Over Time',
        xaxis_title='Trading Days',
        yaxis_title='Drawdown (%)',
        hovermode='x',
        template='plotly_white',
        height=300,
        showlegend=False
    )
    
    fig.update_yaxes(range=[drawdown.min() * 1.1, 5])
    
    return fig.to_html(include_plotlyjs='cdn', div_id='drawdown_chart')

def create_drawdown_duration_histogram(periods_df):
    """
    Create histogram of drawdown durations
    """
    if len(periods_df) == 0:
        return "<div style='padding: 20px; background: #f8f9fa; text-align: center;'>No drawdown periods to display</div>"
    
    fig = go.Figure()
    
    fig.add_trace(go.Histogram(
        x=periods_df['duration_days'],
        nbinsx=20,
        marker=dict(color='#3498DB', line=dict(color='#2C3E50', width=1)),
        hovertemplate='Duration: %{x} days<br>Count: %{y}<extra></extra>'
    ))
    
    # Add median line
    median_duration = periods_df['duration_days'].median()
    fig.add_vline(
        x=median_duration,
        line_dash="dash",
        line_color="red",
        annotation_text=f"Median: {median_duration:.0f} days",
        annotation_position="top"
    )
    
    fig.update_layout(
        title='Drawdown Duration Distribution',
        xaxis_title='Duration (Days)',
        yaxis_title='Frequency',
        template='plotly_white',
        height=300,
        showlegend=False
    )
    
    return fig.to_html(include_plotlyjs='cdn', div_id='drawdown_duration_hist')

def create_walk_forward_chart(results_df):
    """
    Create bar chart showing performance across time periods
    """
    if len(results_df) == 0:
        return "<div style='padding: 20px; background: #f8f9fa; text-align: center;'>No walk-forward data available</div>"
    
    fig = go.Figure()
    
    # Strategy returns
    fig.add_trace(go.Bar(
        x=results_df['period'],
        y=results_df['avg_return_%'],
        name='Strategy Return',
        marker=dict(color=['#E74C3C' if x < 0 else '#2ECC71' for x in results_df['avg_return_%']]),
        hovertemplate='%{x}<br>Return: %{y:.1f}%<extra></extra>'
    ))
    
    # Add zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    
    fig.update_layout(
        title='Walk-Forward Performance Across Time Periods',
        xaxis_title='Period',
        yaxis_title='Average Return (%)',
        template='plotly_white',
        height=400,
        showlegend=False,
        xaxis={'tickangle': -45}
    )
    
    return fig.to_html(include_plotlyjs='cdn', div_id='walk_forward_chart')

def create_metrics_comparison_table(metrics_dict):
    """
    Create formatted HTML table comparing metrics
    """
    html = """
    <table class="metrics-table">
        <thead>
            <tr>
                <th>Metric</th>
                <th>Value</th>
                <th>Benchmark</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for metric_name, data in metrics_dict.items():
        value = data['value']
        benchmark = data.get('benchmark', '-')
        status = data.get('status', 'neutral')
        
        status_icon = {
            'good': '✅',
            'warning': '⚠️',
            'bad': '❌',
            'neutral': '➖'
        }.get(status, '➖')
        
        html += f"""
            <tr>
                <td>{metric_name}</td>
                <td>{value}</td>
                <td>{benchmark}</td>
                <td>{status_icon}</td>
            </tr>
        """
    
    html += """
        </tbody>
    </table>
    """
    
    return html

def create_covid_timeline_chart(covid_results):
    """
    Create timeline showing COVID crash exits and re-entries
    Handles empty/missing data gracefully
    """
    # Handle different input formats
    if isinstance(covid_results, dict):
        results_df = covid_results.get('results_df', pd.DataFrame())
        crash_dates = covid_results.get('crash_dates', {'bottom': '2020-03-23'})
    elif isinstance(covid_results, pd.DataFrame):
        results_df = covid_results
        crash_dates = {'bottom': '2020-03-23'}
    else:
        results_df = pd.DataFrame()
        crash_dates = {'bottom': '2020-03-23'}
    
    # If no data or missing columns, return informative message
    if len(results_df) == 0 or 'exit_date' not in results_df.columns:
        return """
        <div style='padding: 40px; text-align: center; background: linear-gradient(135deg, #fff3cd 0%, #ffe69c 100%); 
                    border-radius: 10px; border-left: 4px solid #ffc107;'>
            <h3 style='color: #856404; margin-bottom: 15px;'>⚠️ COVID Crash Data Not Available</h3>
            <p style='color: #856404; font-size: 0.95em; line-height: 1.6;'>
                The stocks in your filtered universe may not have been publicly traded in early 2020,
                or they didn't generate exit signals during the COVID crash period (Feb-March 2020).
            </p>
            <p style='color: #856404; font-size: 0.9em; margin-top: 10px;'>
                <strong>Note:</strong> Many of your high-quality stocks like COIN, PLTR, and others 
                either IPO'd after 2020 or have limited historical data.
            </p>
        </div>
        """
    
    fig = go.Figure()
    
    # Exit dates
    try:
        exits = results_df[results_df['exit_date'] != 'Never']
        if len(exits) > 0:
            exit_dates = pd.to_datetime(exits['exit_date'])
            fig.add_trace(go.Scatter(
                x=exit_dates,
                y=exits['symbol'],
                mode='markers',
                name='Exit Signal',
                marker=dict(symbol='x', size=12, color='red'),
                hovertemplate='%{y}<br>Exit: %{x}<extra></extra>'
            ))
    except Exception:
        pass
    
    # Re-entry dates
    try:
        if 're_entry_date' in results_df.columns:
            re_entries = results_df[results_df['re_entry_date'] != 'Never']
            if len(re_entries) > 0:
                re_entry_dates = pd.to_datetime(re_entries['re_entry_date'])
                fig.add_trace(go.Scatter(
                    x=re_entry_dates,
                    y=re_entries['symbol'],
                    mode='markers',
                    name='Re-Entry Signal',
                    marker=dict(symbol='circle', size=12, color='green'),
                    hovertemplate='%{y}<br>Re-entry: %{x}<extra></extra>'
                ))
    except Exception:
        pass
    
    # Add crash bottom line
    if 'bottom' in crash_dates:
        try:
            fig.add_vline(
                x=crash_dates['bottom'],
                line_dash="dash",
                line_color="orange",
                annotation_text="Market Bottom",
                annotation_position="top"
            )
        except Exception:
            pass
    
    # If figure has no data, return message
    if len(fig.data) == 0:
        return """
        <div style='padding: 40px; text-align: center; background: #f8f9fa; border-radius: 10px;'>
            <h3 style='color: #6c757d;'>📊 No COVID Crash Signals Detected</h3>
            <p style='color: #6c757d;'>No exit or re-entry signals were generated during the test period.</p>
        </div>
        """
    
    fig.update_layout(
        title='COVID Crash: Exit and Re-Entry Timing',
        xaxis_title='Date',
        yaxis_title='Symbol',
        template='plotly_white',
        height=400,
        showlegend=True
    )
    
    return fig.to_html(include_plotlyjs='cdn', div_id='covid_timeline')