"""
Professional Trade Tracker Excel Generator
===========================================
Creates institutional-grade performance tracking workbook with:
- Trade log with all transactions
- Performance metrics dashboard
- Monthly/yearly performance breakdown
- Drawdown analysis
- Position tracking
- Risk metrics

Usage:
    python create_trade_tracker.py
    
This creates: trade_tracker.xlsx with multiple sheets
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
from openpyxl.chart import LineChart, Reference, BarChart
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule


class TradeTrackerBuilder:
    """
    Builds professional-grade trade tracking Excel workbook
    """
    
    def __init__(self):
        self.wb = Workbook()
        
        # Remove default sheet
        if 'Sheet' in self.wb.sheetnames:
            self.wb.remove(self.wb['Sheet'])
        
        # Color scheme (professional blue/green)
        self.colors = {
            'header': '2E86AB',      # Blue header
            'positive': '06D6A0',    # Green for gains
            'negative': 'EF476F',    # Red for losses
            'neutral': 'F8F9FA',     # Light gray
            'dark': '073B4C'         # Dark blue
        }
        
        # Border style
        self.thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
    
    def create_trades_sheet(self):
        """
        Sheet 1: Complete trade log
        """
        ws = self.wb.create_sheet("Trade Log", 0)
        
        # Headers
        headers = [
            'Trade #', 'Entry Date', 'Exit Date', 'Symbol', 'Action',
            'Shares', 'Entry Price', 'Exit Price', 'Entry Value', 'Exit Value',
            'Gross P&L', 'Commission', 'Net P&L', 'Return %', 'Hold Days',
            'Win/Loss', 'Strategy', 'Market Regime', 'Notes'
        ]
        
        # Write headers
        for col, header in enumerate(headers, 1):
            cell = ws.cell(1, col, header)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill(start_color=self.colors['header'], 
                                   end_color=self.colors['header'], 
                                   fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.thin_border
        
        # Column widths
        widths = [8, 12, 12, 10, 8, 10, 12, 12, 14, 14, 12, 10, 12, 10, 10, 10, 12, 14, 30]
        for col, width in enumerate(widths, 1):
            ws.column_dimensions[chr(64 + col)].width = width
        
        # Freeze header row
        ws.freeze_panes = 'A2'
        
        # Add sample trade
        sample_trade = [
            1, datetime(2025, 1, 15), datetime(2025, 2, 20), 'AAPL', 'LONG',
            100, 150.25, 165.80, 15025, 16580, 1555, 2, 1553, 10.33, 36,
            'Win', 'VPVMA', 'Bull', 'Strong momentum entry'
        ]
        
        for col, value in enumerate(sample_trade, 1):
            cell = ws.cell(2, col, value)
            cell.border = self.thin_border
            
            # Format numbers
            if col in [7, 8]:  # Prices
                cell.number_format = '$#,##0.00'
            elif col in [9, 10, 11, 12, 13]:  # Dollar amounts
                cell.number_format = '$#,##0.00'
            elif col == 14:  # Percentage
                cell.number_format = '0.00%'
            elif col in [2, 3]:  # Dates
                cell.number_format = 'MM/DD/YYYY'
        
        # Add conditional formatting for P&L
        ws.conditional_formatting.add(
            'M2:M1000',
            ColorScaleRule(
                start_type='num', start_value=-1000, start_color=self.colors['negative'],
                mid_type='num', mid_value=0, mid_color='FFFFFF',
                end_type='num', end_value=1000, end_color=self.colors['positive']
            )
        )
        
        # Instructions
        ws.cell(1000, 1, "Instructions: Add each closed trade as a new row. Metrics will auto-calculate.")
        ws.cell(1000, 1).font = Font(italic=True, size=9)
        
        return ws
    
    def create_dashboard_sheet(self):
        """
        Sheet 2: Performance metrics dashboard
        """
        ws = self.wb.create_sheet("Dashboard", 1)
        
        # Title
        ws.merge_cells('A1:F1')
        title = ws['A1']
        title.value = "VPVMA Trading Performance Dashboard"
        title.font = Font(size=18, bold=True, color=self.colors['dark'])
        title.alignment = Alignment(horizontal='center', vertical='center')
        
        row = 3
        
        # Section 1: Overall Performance
        ws.merge_cells(f'A{row}:F{row}')
        section = ws.cell(row, 1, "Overall Performance")
        section.font = Font(size=14, bold=True, color='FFFFFF')
        section.fill = PatternFill(start_color=self.colors['header'], 
                                   end_color=self.colors['header'], 
                                   fill_type='solid')
        section.alignment = Alignment(horizontal='center')
        row += 1
        
        metrics = [
            ('Total Trades', '=COUNTA(\'Trade Log\'!A:A)-1', '0'),
            ('Win Rate', '=COUNTIF(\'Trade Log\'!P:P,"Win")/COUNTA(\'Trade Log\'!P:P)', '0.00%'),
            ('Total P&L', '=SUM(\'Trade Log\'!M:M)', '$#,##0.00'),
            ('Average Win', '=AVERAGEIF(\'Trade Log\'!P:P,"Win",\'Trade Log\'!M:M)', '$#,##0.00'),
            ('Average Loss', '=AVERAGEIF(\'Trade Log\'!P:P,"Loss",\'Trade Log\'!M:M)', '$#,##0.00'),
            ('Profit Factor', '=ABS(SUMIF(\'Trade Log\'!P:P,"Win",\'Trade Log\'!M:M)/SUMIF(\'Trade Log\'!P:P,"Loss",\'Trade Log\'!M:M))', '0.00'),
            ('Average Return %', '=AVERAGE(\'Trade Log\'!N:N)', '0.00%'),
            ('Average Hold Days', '=AVERAGE(\'Trade Log\'!O:O)', '0'),
        ]
        
        for metric, formula, num_format in metrics:
            ws.cell(row, 1, metric).font = Font(bold=True)
            value_cell = ws.cell(row, 2, formula)
            value_cell.number_format = num_format
            value_cell.font = Font(size=12)
            row += 1
        
        row += 2
        
        # Section 2: Risk Metrics
        ws.merge_cells(f'A{row}:F{row}')
        section = ws.cell(row, 1, "Risk Metrics")
        section.font = Font(size=14, bold=True, color='FFFFFF')
        section.fill = PatternFill(start_color=self.colors['header'], 
                                   end_color=self.colors['header'], 
                                   fill_type='solid')
        section.alignment = Alignment(horizontal='center')
        row += 1
        
        risk_metrics = [
            ('Max Win', '=MAX(\'Trade Log\'!M:M)', '$#,##0.00'),
            ('Max Loss', '=MIN(\'Trade Log\'!M:M)', '$#,##0.00'),
            ('Max Drawdown', '=MIN(\'Monthly Performance\'!E:E)', '0.00%'),
            ('Sharpe Ratio', '=(AVERAGE(\'Trade Log\'!N:N)-0)/STDEV(\'Trade Log\'!N:N)*SQRT(252)', '0.00'),
            ('Sortino Ratio', '=AVERAGE(\'Trade Log\'!N:N)/STDEV(IF(\'Trade Log\'!N:N<0,\'Trade Log\'!N:N))*SQRT(252)', '0.00'),
        ]
        
        for metric, formula, num_format in risk_metrics:
            ws.cell(row, 1, metric).font = Font(bold=True)
            value_cell = ws.cell(row, 2, formula)
            value_cell.number_format = num_format
            value_cell.font = Font(size=12)
            row += 1
        
        row += 2
        
        # Section 3: By Strategy
        ws.merge_cells(f'A{row}:F{row}')
        section = ws.cell(row, 1, "Performance by Market Regime")
        section.font = Font(size=14, bold=True, color='FFFFFF')
        section.fill = PatternFill(start_color=self.colors['header'], 
                                   end_color=self.colors['header'], 
                                   fill_type='solid')
        section.alignment = Alignment(horizontal='center')
        row += 1
        
        # Headers for regime table
        regime_headers = ['Regime', 'Trades', 'Win Rate', 'Avg P&L', 'Total P&L']
        for col, header in enumerate(regime_headers, 1):
            cell = ws.cell(row, col, header)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color=self.colors['neutral'], 
                                   end_color=self.colors['neutral'], 
                                   fill_type='solid')
            cell.border = self.thin_border
        row += 1
        
        # Bull regime row
        ws.cell(row, 1, "Bull")
        ws.cell(row, 2, '=COUNTIF(\'Trade Log\'!R:R,"Bull")')
        ws.cell(row, 3, '=COUNTIFS(\'Trade Log\'!R:R,"Bull",\'Trade Log\'!P:P,"Win")/COUNTIF(\'Trade Log\'!R:R,"Bull")').number_format = '0.00%'
        ws.cell(row, 4, '=AVERAGEIF(\'Trade Log\'!R:R,"Bull",\'Trade Log\'!M:M)').number_format = '$#,##0.00'
        ws.cell(row, 5, '=SUMIF(\'Trade Log\'!R:R,"Bull",\'Trade Log\'!M:M)').number_format = '$#,##0.00'
        row += 1
        
        # Bear regime row
        ws.cell(row, 1, "Bear")
        ws.cell(row, 2, '=COUNTIF(\'Trade Log\'!R:R,"Bear")')
        ws.cell(row, 3, '=COUNTIFS(\'Trade Log\'!R:R,"Bear",\'Trade Log\'!P:P,"Win")/COUNTIF(\'Trade Log\'!R:R,"Bear")').number_format = '0.00%'
        ws.cell(row, 4, '=AVERAGEIF(\'Trade Log\'!R:R,"Bear",\'Trade Log\'!M:M)').number_format = '$#,##0.00'
        ws.cell(row, 5, '=SUMIF(\'Trade Log\'!R:R,"Bear",\'Trade Log\'!M:M)').number_format = '$#,##0.00'
        
        # Set column widths
        for col in range(1, 7):
            ws.column_dimensions[chr(64 + col)].width = 18
        
        return ws
    
    def create_monthly_performance_sheet(self):
        """
        Sheet 3: Monthly performance breakdown
        """
        ws = self.wb.create_sheet("Monthly Performance", 2)
        
        # Headers
        headers = ['Year', 'Month', 'Trades', 'Win Rate', 'P&L', 'Return %', 'Cumulative P&L']
        
        for col, header in enumerate(headers, 1):
            cell = ws.cell(1, col, header)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill(start_color=self.colors['header'], 
                                   end_color=self.colors['header'], 
                                   fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.thin_border
        
        # Sample data structure
        sample_months = [
            (2025, 'January', 15, 0.60, 2450, 2.45, 2450),
            (2025, 'February', 18, 0.56, 1890, 1.89, 4340),
            (2025, 'March', 20, 0.65, 3120, 3.12, 7460),
        ]
        
        row = 2
        for year, month, trades, win_rate, pnl, ret, cum_pnl in sample_months:
            ws.cell(row, 1, year)
            ws.cell(row, 2, month)
            ws.cell(row, 3, trades)
            ws.cell(row, 4, win_rate).number_format = '0.00%'
            ws.cell(row, 5, pnl).number_format = '$#,##0.00'
            ws.cell(row, 6, ret).number_format = '0.00%'
            ws.cell(row, 7, cum_pnl).number_format = '$#,##0.00'
            
            for col in range(1, 8):
                ws.cell(row, col).border = self.thin_border
            
            row += 1
        
        # Conditional formatting for P&L
        ws.conditional_formatting.add(
            'E2:E100',
            ColorScaleRule(
                start_type='num', start_value=-5000, start_color=self.colors['negative'],
                mid_type='num', mid_value=0, mid_color='FFFFFF',
                end_type='num', end_value=5000, end_color=self.colors['positive']
            )
        )
        
        # Column widths
        widths = [8, 12, 10, 12, 15, 12, 18]
        for col, width in enumerate(widths, 1):
            ws.column_dimensions[chr(64 + col)].width = width
        
        ws.freeze_panes = 'A2'
        
        # Add chart
        chart = LineChart()
        chart.title = "Cumulative P&L Over Time"
        chart.style = 13
        chart.y_axis.title = "Cumulative P&L ($)"
        chart.x_axis.title = "Month"
        
        data = Reference(ws, min_col=7, min_row=1, max_row=row-1)
        cats = Reference(ws, min_col=2, min_row=2, max_row=row-1)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        
        ws.add_chart(chart, "I2")
        
        return ws
    
    def create_drawdown_sheet(self):
        """
        Sheet 4: Drawdown analysis
        """
        ws = self.wb.create_sheet("Drawdown Analysis", 3)
        
        # Headers
        headers = ['Date', 'Equity', 'Peak Equity', 'Drawdown $', 'Drawdown %', 'Underwater Days']
        
        for col, header in enumerate(headers, 1):
            cell = ws.cell(1, col, header)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill(start_color=self.colors['header'], 
                                   end_color=self.colors['header'], 
                                   fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.thin_border
        
        # Sample data
        base_equity = 100000
        sample_data = [
            (datetime(2025, 1, 31), 102450, 102450, 0, 0, 0),
            (datetime(2025, 2, 28), 104340, 104340, 0, 0, 0),
            (datetime(2025, 3, 31), 107460, 107460, 0, 0, 0),
            (datetime(2025, 4, 30), 105230, 107460, -2230, -2.07, 30),
        ]
        
        row = 2
        for date, equity, peak, dd_dollar, dd_pct, days in sample_data:
            ws.cell(row, 1, date).number_format = 'MM/DD/YYYY'
            ws.cell(row, 2, equity).number_format = '$#,##0.00'
            ws.cell(row, 3, peak).number_format = '$#,##0.00'
            ws.cell(row, 4, dd_dollar).number_format = '$#,##0.00'
            ws.cell(row, 5, dd_pct / 100).number_format = '0.00%'
            ws.cell(row, 6, days)
            
            for col in range(1, 7):
                ws.cell(row, col).border = self.thin_border
            
            row += 1
        
        # Conditional formatting
        ws.conditional_formatting.add(
            'E2:E100',
            ColorScaleRule(
                start_type='num', start_value=-0.3, start_color=self.colors['negative'],
                mid_type='num', mid_value=-0.1, mid_color='FFEB9C',
                end_type='num', end_value=0, end_color='FFFFFF'
            )
        )
        
        # Column widths
        widths = [12, 15, 15, 15, 15, 15]
        for col, width in enumerate(widths, 1):
            ws.column_dimensions[chr(64 + col)].width = width
        
        ws.freeze_panes = 'A2'
        
        # Add chart
        chart = LineChart()
        chart.title = "Equity Curve with Drawdowns"
        chart.style = 13
        
        # Equity line
        equity_data = Reference(ws, min_col=2, min_row=1, max_row=row-1)
        dates = Reference(ws, min_col=1, min_row=2, max_row=row-1)
        chart.add_data(equity_data, titles_from_data=True)
        chart.set_categories(dates)
        
        ws.add_chart(chart, "H2")
        
        return ws
    
    def create_positions_sheet(self):
        """
        Sheet 5: Current positions tracker
        """
        ws = self.wb.create_sheet("Current Positions", 4)
        
        # Headers
        headers = [
            'Symbol', 'Entry Date', 'Shares', 'Entry Price', 'Current Price',
            'Entry Value', 'Current Value', 'Unrealized P&L', 'Unrealized %',
            'Days Held', 'Stop Loss', 'Target', 'Notes'
        ]
        
        for col, header in enumerate(headers, 1):
            cell = ws.cell(1, col, header)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill(start_color=self.colors['header'], 
                                   end_color=self.colors['header'], 
                                   fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.thin_border
        
        # Sample position
        sample_position = [
            'AAPL', datetime(2025, 11, 15), 100, 225.50, 230.75,
            22550, 23075, 525, 2.33, 3, 215.00, 240.00, 'Strong momentum'
        ]
        
        for col, value in enumerate(sample_position, 1):
            cell = ws.cell(2, col, value)
            cell.border = self.thin_border
            
            # Format
            if col == 2:  # Date
                cell.number_format = 'MM/DD/YYYY'
            elif col in [4, 5, 11, 12]:  # Prices
                cell.number_format = '$#,##0.00'
            elif col in [6, 7, 8]:  # Dollar amounts
                cell.number_format = '$#,##0.00'
            elif col == 9:  # Percentage
                cell.number_format = '0.00%'
        
        # Summary row
        summary_row = 10
        ws.cell(summary_row, 1, "TOTAL").font = Font(bold=True)
        ws.cell(summary_row, 6, f'=SUM(F2:F{summary_row-1})').number_format = '$#,##0.00'
        ws.cell(summary_row, 6).font = Font(bold=True)
        ws.cell(summary_row, 7, f'=SUM(G2:G{summary_row-1})').number_format = '$#,##0.00'
        ws.cell(summary_row, 7).font = Font(bold=True)
        ws.cell(summary_row, 8, f'=SUM(H2:H{summary_row-1})').number_format = '$#,##0.00'
        ws.cell(summary_row, 8).font = Font(bold=True)
        
        # Conditional formatting
        ws.conditional_formatting.add(
            'H2:H100',
            ColorScaleRule(
                start_type='num', start_value=-1000, start_color=self.colors['negative'],
                mid_type='num', mid_value=0, mid_color='FFFFFF',
                end_type='num', end_value=1000, end_color=self.colors['positive']
            )
        )
        
        # Column widths
        widths = [10, 12, 10, 12, 12, 14, 14, 14, 12, 10, 12, 12, 30]
        for col, width in enumerate(widths, 1):
            ws.column_dimensions[chr(64 + col)].width = width
        
        ws.freeze_panes = 'A2'
        
        return ws
    
    def create_statistics_sheet(self):
        """
        Sheet 6: Advanced statistics
        """
        ws = self.wb.create_sheet("Statistics", 5)
        
        # Title
        ws.merge_cells('A1:D1')
        title = ws['A1']
        title.value = "Advanced Trading Statistics"
        title.font = Font(size=16, bold=True, color=self.colors['dark'])
        title.alignment = Alignment(horizontal='center')
        
        row = 3
        
        # Win/Loss Distribution
        ws.merge_cells(f'A{row}:D{row}')
        section = ws.cell(row, 1, "Win/Loss Distribution")
        section.font = Font(size=12, bold=True, color='FFFFFF')
        section.fill = PatternFill(start_color=self.colors['header'], 
                                   end_color=self.colors['header'], 
                                   fill_type='solid')
        row += 1
        
        stats = [
            ('Total Wins', '=COUNTIF(\'Trade Log\'!P:P,"Win")'),
            ('Total Losses', '=COUNTIF(\'Trade Log\'!P:P,"Loss")'),
            ('Longest Win Streak', 'Manual'),
            ('Longest Loss Streak', 'Manual'),
            ('Largest Win $', '=MAX(\'Trade Log\'!M:M)'),
            ('Largest Loss $', '=MIN(\'Trade Log\'!M:M)'),
            ('Average Trade Duration', '=AVERAGE(\'Trade Log\'!O:O)'),
        ]
        
        for label, formula in stats:
            ws.cell(row, 1, label).font = Font(bold=True)
            ws.cell(row, 2, formula)
            row += 1
        
        row += 2
        
        # Returns Distribution
        ws.merge_cells(f'A{row}:D{row}')
        section = ws.cell(row, 1, "Returns Distribution")
        section.font = Font(size=12, bold=True, color='FFFFFF')
        section.fill = PatternFill(start_color=self.colors['header'], 
                                   end_color=self.colors['header'], 
                                   fill_type='solid')
        row += 1
        
        return_stats = [
            ('Mean Return %', '=AVERAGE(\'Trade Log\'!N:N)', '0.00%'),
            ('Median Return %', '=MEDIAN(\'Trade Log\'!N:N)', '0.00%'),
            ('Std Dev Return %', '=STDEV(\'Trade Log\'!N:N)', '0.00%'),
            ('Skewness', 'Manual', '0.00'),
            ('Kurtosis', 'Manual', '0.00'),
        ]
        
        for label, formula, num_format in return_stats:
            ws.cell(row, 1, label).font = Font(bold=True)
            cell = ws.cell(row, 2, formula)
            cell.number_format = num_format
            row += 1
        
        # Column widths
        ws.column_dimensions['A'].width = 25
        ws.column_dimensions['B'].width = 20
        
        return ws
    
    def build(self, output_path='trade_tracker.xlsx'):
        """
        Build complete workbook
        """
        print("Building professional trade tracker...")
        
        # Create all sheets
        print("  Creating Trade Log sheet...")
        self.create_trades_sheet()
        
        print("  Creating Dashboard sheet...")
        self.create_dashboard_sheet()
        
        print("  Creating Monthly Performance sheet...")
        self.create_monthly_performance_sheet()
        
        print("  Creating Drawdown Analysis sheet...")
        self.create_drawdown_sheet()
        
        print("  Creating Current Positions sheet...")
        self.create_positions_sheet()
        
        print("  Creating Statistics sheet...")
        self.create_statistics_sheet()
        
        # Save workbook
        self.wb.save(output_path)
        print(f"\n✅ Trade tracker created: {output_path}")
        print(f"\nSheets created:")
        for sheet in self.wb.sheetnames:
            print(f"  • {sheet}")
        
        return output_path


def main():
    """
    Main execution
    """
    print("="*60)
    print("PROFESSIONAL TRADE TRACKER GENERATOR")
    print("="*60)
    print()
    
    builder = TradeTrackerBuilder()
    output_file = builder.build('trade_tracker.xlsx')
    
    print("\n" + "="*60)
    print("USAGE INSTRUCTIONS")
    print("="*60)
    print("""
1. TRADE LOG:
   - Add each closed trade as a new row
   - Enter: Entry date, exit date, symbol, shares, prices
   - Win/Loss will auto-calculate
   
2. DASHBOARD:
   - Metrics auto-update from Trade Log
   - Shows overall performance, risk metrics, regime analysis
   
3. MONTHLY PERFORMANCE:
   - Calculate monthly from Trade Log
   - Track cumulative performance
   
4. CURRENT POSITIONS:
   - Manually update current holdings
   - Update "Current Price" daily
   - Track unrealized P&L
   
5. STATISTICS:
   - Advanced metrics for deep analysis
   - Some require manual calculation
    """)
    
    print("="*60)
    print("Ready to track your trades! 📊")
    print("="*60)
    
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)