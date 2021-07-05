# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.template import loader
from django.http import HttpResponse
from django import template
from django.db import connection
from django.http import JsonResponse
import pandas as pd
import numpy as np
import datetime


@login_required(login_url="/login/")
def index(request):
    
    context = {}
    context['segment'] = 'index'


    lastBusyDay = datetime.datetime.today()
    shift = datetime.timedelta(max(1, (lastBusyDay.weekday() + 6) % 7 - 3))
    lastBusyDay = (lastBusyDay - shift).replace(hour=0, minute=0, second=0, microsecond=0)

    nameIndex = "CAC 40"
    sql_select = "SELECT date_stock_option, open, high, low, close, adj_close, volume "
    sql_from = "FROM ticker NATURAL JOIN stock_option "
    sql_where = "WHERE ticker.nom = '" + nameIndex + "'"
    IndexSymbol = pd.read_sql_query(sql=(sql_select + sql_from + sql_where),
                                    con=connection,
                                    parse_dates="date_stock_option")\
        .set_index('date_stock_option')
    IndexSymbol.index.name = "date"
    IndexSymbol_adj_close = IndexSymbol[['adj_close']].reset_index()
    IndexSymbol_adj_close_start = IndexSymbol_adj_close[IndexSymbol_adj_close['date'] == lastBusyDay]
    context['cac40'] = format(IndexSymbol_adj_close_start['adj_close'].item(), ",.2f").replace(",", " ")

    sql_select = "SELECT date_execution, ticker, quantite, unit_cost, tax, (quantite * unit_cost + tax) As 'cost_basis' "
    sql_from = "FROM auth_user NATURAL JOIN portefolio NATURAL JOIN position NATURAL JOIN ticker "
    sql_where = "WHERE is_principal=1"
    portfolio_df = pd.read_sql_query(sql=(sql_select + sql_from + sql_where),
                                     con=connection)
    portfolio_df["Start of Year"] = lastBusyDay

    all_data = pd.read_sql_query(sql="SELECT * FROM view_data_stock_option",
                           con=connection,
                           parse_dates="date")\
        .set_index(['ticker', 'date'])
    adj_close = all_data[['adj_close']].reset_index()
    adj_close_start = adj_close[adj_close['date'] == lastBusyDay]

    # Grab the latest stock close price
    adj_close_latest = adj_close[adj_close['date'] == lastBusyDay]
    adj_close_latest.set_index('ticker', inplace=True)
    portfolio_df.set_index(['ticker'], inplace=True)

    # Merge the portfolio dataframe with the adj close dataframe; they are being joined by their indexes.
    merged_portfolio = pd.merge(portfolio_df, adj_close_latest, left_index=True, right_index=True)
    # The below creates a new column which is the ticker return; takes the latest adjusted close for each position
    # and divides that by the initial share cost.

    merged_portfolio['ticker return'] = merged_portfolio['adj_close'] / merged_portfolio['unit_cost'] - 1
    merged_portfolio.reset_index(inplace=True)
    # Here we are merging the new dataframe with the IndexSymbol adjusted closes since the is start price based on
    # each ticker's acquisition date and IndexSymbol close date.
    merged_portfolio.date_execution = merged_portfolio.date_execution.astype('datetime64[ns]')
    #IndexSymbol_adj_close.date.astype('datetime64[ns]')
    #print(merged_portfolio.info())
    #print(IndexSymbol_adj_close.info())
    merged_portfolio_is = pd.merge(merged_portfolio, IndexSymbol_adj_close, left_on='date_execution', right_on='date')
    del merged_portfolio_is['date_y']

    merged_portfolio_is.rename(columns={'date_x': 'Latest Date', 'adj_close_x': 'Ticker Adj Close'
        , 'adj_close_y': 'IndexSymbol Initial Close'}, inplace=True)
    # This new column determines what IndexSymbol equivalent purchase would have been at purchase date of stock.
    merged_portfolio_is['Equiv is Shares'] = merged_portfolio_is['cost_basis'] / merged_portfolio_is[
        'IndexSymbol Initial Close']
    # We are joining the developing dataframe with the IndexSymbol closes again, this time with the latest close for is.
    merged_portfolio_is_latest = pd.merge(merged_portfolio_is, IndexSymbol_adj_close, left_on='Latest Date',
                                          right_on='date')
    # Once again need to delete the new Date column added as it's redundant to Latest Date.
    # Modify Adj Close from the is dataframe to distinguish it by calling it the IndexSymbol Latest Close.

    del merged_portfolio_is_latest['date']

    merged_portfolio_is_latest.rename(columns={'adj_close': 'IndexSymbol Latest Close'}, inplace=True)
    # Percent return of is from acquisition date of position through latest trading day.
    merged_portfolio_is_latest['is Return'] = merged_portfolio_is_latest['IndexSymbol Latest Close'] / \
                                              merged_portfolio_is_latest['IndexSymbol Initial Close'] - 1

    # This is a new column which takes the tickers return and subtracts the IndexSymbol equivalent range return.
    merged_portfolio_is_latest['Abs. Return Compare'] = merged_portfolio_is_latest['ticker return'] - \
                                                        merged_portfolio_is_latest['is Return']

    # This is a new column where we calculate the ticker's share value by multiplying the original quantity by the latest close.
    merged_portfolio_is_latest['Ticker Share Value'] = merged_portfolio_is_latest['quantite'] * \
                                                       merged_portfolio_is_latest['Ticker Adj Close']

    # We calculate the equivalent IndexSymbol Value if we take the original is shares * the latest IndexSymbol share price.
    merged_portfolio_is_latest['IndexSymbol Value'] = merged_portfolio_is_latest['Equiv is Shares'] * \
                                                      merged_portfolio_is_latest['IndexSymbol Latest Close']

    # This is a new column where we take the current market value for the shares and subtract the IndexSymbol value.
    merged_portfolio_is_latest['Abs Value Compare'] = merged_portfolio_is_latest['Ticker Share Value'] - \
                                                      merged_portfolio_is_latest['IndexSymbol Value']

    # This column calculates profit / loss for stock position.
    merged_portfolio_is_latest['Stock Gain / (Loss)'] = merged_portfolio_is_latest['Ticker Share Value'] - \
                                                        merged_portfolio_is_latest['cost_basis']

    # This column calculates profit / loss for IndexSymbol.
    merged_portfolio_is_latest['IndexSymbol Gain / (Loss)'] = merged_portfolio_is_latest['IndexSymbol Value'] - \
                                                              merged_portfolio_is_latest['cost_basis']
    html_template = loader.get_template( 'index.html' )

    # Merge the overall dataframe with the adj close start of year dataframe for YTD tracking of tickers.
    # Should not need to do the outer join;

    merged_portfolio_is_latest_YTD = pd.merge(merged_portfolio_is_latest, adj_close_start, on='ticker')
    # , how='outer'
    # Deleting date again as it's an unnecessary column.  Explaining that new column is the Ticker Start of Year Close.

    del merged_portfolio_is_latest_YTD['date']

    merged_portfolio_is_latest_YTD.rename(columns={'adj_close': 'Ticker Start Year Close'}, inplace=True)
    # Join the IndexSymbol start of year with current dataframe for IndexSymbol ytd comparisons to tickers.

    merged_portfolio_is_latest_YTD_is = pd.merge(merged_portfolio_is_latest_YTD, IndexSymbol_adj_close_start,
                                                 left_on='Start of Year', right_on='date')
    # Deleting another unneeded Date column.

    del merged_portfolio_is_latest_YTD_is['date']

    # Renaming so that it's clear this column is IndexSymbol start of year close.
    merged_portfolio_is_latest_YTD_is.rename(columns={'adj_close': 'is Start Year Close'}, inplace=True)

    # YTD return for portfolio position.
    merged_portfolio_is_latest_YTD_is['Share YTD'] = merged_portfolio_is_latest_YTD_is['Ticker Adj Close'] / \
                                                     merged_portfolio_is_latest_YTD_is['Ticker Start Year Close'] - 1

    # YTD return for is to run compares.
    merged_portfolio_is_latest_YTD_is['IndexSymbol YTD'] = merged_portfolio_is_latest_YTD_is[
                                                               'IndexSymbol Latest Close'] / \
                                                           merged_portfolio_is_latest_YTD_is['is Start Year Close'] - 1
    merged_portfolio_is_latest_YTD_is = merged_portfolio_is_latest_YTD_is.sort_values(by='ticker', ascending=True)

    # Cumulative sum of original investment
    # merged_portfolio_is_latest_YTD_is['Cum Invst'] = merged_portfolio_is_latest_YTD_is['Cost Basis'].cumsum()
    merged_portfolio_is_latest_YTD_is['Cum Invst'] = merged_portfolio_is_latest_YTD_is['cost_basis']

    # Cumulative sum of Ticker Share Value (latest FMV based on initial quantity purchased).
    # merged_portfolio_is_latest_YTD_is['Cum Ticker Returns'] = merged_portfolio_is_latest_YTD_is['Ticker Share Value'].cumsum()
    merged_portfolio_is_latest_YTD_is['Cum Ticker Returns'] = merged_portfolio_is_latest_YTD_is['Ticker Share Value']

    # Cumulative sum of is Share Value (latest FMV driven off of initial is equiv purchase).
    # merged_portfolio_is_latest_YTD_is['Cum is Returns'] = merged_portfolio_is_latest_YTD_is['IndexSymbol Value'].cumsum()
    merged_portfolio_is_latest_YTD_is['Cum is Returns'] = merged_portfolio_is_latest_YTD_is['IndexSymbol Value']

    # Cumulative CoC multiple return for stock investments
    merged_portfolio_is_latest_YTD_is['Cum Ticker ROI Mult'] = merged_portfolio_is_latest_YTD_is['Cum Ticker Returns'] / \
                                                               merged_portfolio_is_latest_YTD_is['Cum Invst']
    # Need to factor in that some positions were purchased much more recently than others.
    # Join adj_close dataframe with portfolio in order to have acquisition date.

    portfolio_df.reset_index(inplace=True)

    adj_close_acq_date = pd.merge(adj_close, portfolio_df, on='ticker')
    # delete_columns = ['Quantity', 'Unit Cost', 'Cost Basis', 'Start of Year']

    del adj_close_acq_date['quantite']
    del adj_close_acq_date['unit_cost']
    del adj_close_acq_date['cost_basis']
    del adj_close_acq_date['Start of Year']
    adj_close_acq_date['date_execution'] = adj_close_acq_date['date_execution'].astype('datetime64[ns]')
    # Sort by these columns in this order in order to make it clearer where compare for each position should begin.
    adj_close_acq_date.sort_values(by=['ticker', 'date_execution', 'date'], ascending=[True, True, True],
                                   inplace=True)

    # Anything less than 0 means that the stock close was prior to acquisition.
    adj_close_acq_date['Date Delta'] = adj_close_acq_date['date'] - adj_close_acq_date['date_execution']

    adj_close_acq_date['Date Delta'] = adj_close_acq_date[['Date Delta']].apply(pd.to_numeric)
    # Modified the dataframe being evaluated to look at highest close which occurred after Acquisition Date (aka, not prior to purchase).

    adj_close_acq_date_modified = adj_close_acq_date[adj_close_acq_date['Date Delta'] == 0]

    # This pivot table will index on the Ticker and Acquisition Date, and find the max adjusted close.
    adj_close_pivot = adj_close_acq_date_modified.pivot_table(index=['ticker', 'date_execution'], values='adj_close',
                                                              aggfunc=np.max)
    adj_close_pivot.reset_index(inplace=True)
    # Merge the adj close pivot table with the adj_close table in order to grab the date of the Adj Close High (good to know).

    adj_close_pivot_merged = pd.merge(adj_close_pivot, adj_close
                                      , on=['ticker', 'adj_close'])
    # adj_close_pivot_merged = pd.merge(adj_close_pivot[['Ticker','Acquisition Date']], adj_close, how='left', left_on=['Ticker', 'Acquisition Date'], right_on=['Ticker', 'Date'])
    # Merge the Adj Close pivot table with the master dataframe to have the closing high since you have owned the stock.

    merged_portfolio_is_latest_YTD_is_closing_high = pd.merge(merged_portfolio_is_latest_YTD_is, adj_close_pivot_merged
                                                              , on=['ticker', 'date_execution'])

    # Renaming so that it's clear that the new columns are two year closing high and two year closing high date.
    merged_portfolio_is_latest_YTD_is_closing_high.rename(
        columns={'adj_close': 'Closing High Adj Close', 'date': 'Closing High Adj Close Date'}, inplace=True)

    merged_portfolio_is_latest_YTD_is_closing_high['Pct off High'] = merged_portfolio_is_latest_YTD_is_closing_high[
                                                                         'Ticker Adj Close'] / \
                                                                     merged_portfolio_is_latest_YTD_is_closing_high[
                                                                         'Closing High Adj Close'] - 1
    # Ploty is an outstanding resource for interactive charts.
    balance = merged_portfolio_is_latest_YTD_is_closing_high['Cum Ticker Returns'].sum()
    balance_init = merged_portfolio_is_latest_YTD_is_closing_high['cost_basis'].sum()
    performance = (balance - balance_init) / balance_init * 100

    context['balance'] = format(balance, ",.2f").replace(",", " ") + " €"
    context['performance'] = format(performance, ",.2f").replace(",", " ") + " %"

    lastPLJ = lastBusyDay - datetime.timedelta(max(1, (lastBusyDay.weekday() + 6) % 7 - 3))
    PLJ = pd.merge(adj_close[adj_close.date.isin([lastBusyDay])], adj_close[adj_close.date.isin([lastPLJ])],
                   on='ticker')

    PLJ['PL J'] = PLJ['adj_close_x'] - PLJ['adj_close_y']
    del PLJ['date_x']
    del PLJ['adj_close_x']
    del PLJ['date_y']
    del PLJ['adj_close_y']
    merged_portfolio_is_latest = pd.merge(merged_portfolio_is_latest, PLJ, on='ticker')
    merged_portfolio_is_latest['Cum PLJ'] = merged_portfolio_is_latest['PL J'] * merged_portfolio_is_latest['quantite']
    PL_journee = merged_portfolio_is_latest['Cum PLJ'].sum()
    PL_posOuverte = merged_portfolio_is_latest['Stock Gain / (Loss)'].sum()

    context['PNL_Day'] = format(PL_journee, ",.2f").replace(",", " ") + " €"
    context['PNL_PositionOpen'] = format(PL_posOuverte, ",.2f").replace(",", " ") + " €"

    # Figure 1
    context['fig1_label'] = list(merged_portfolio_is_latest_YTD_is_closing_high['ticker'].values)
    context['fig1_cum_invt'] = list(merged_portfolio_is_latest_YTD_is_closing_high['Cum Invst'].values)
    context['fig1_cum_is_return'] = list(merged_portfolio_is_latest_YTD_is_closing_high['Cum is Returns'].values)
    context['fig1_cum_ticker_returns'] = list(merged_portfolio_is_latest_YTD_is_closing_high['Cum Ticker Returns'].values)
    context['fig1_cum_ticker_roi'] = list(merged_portfolio_is_latest_YTD_is_closing_high['Cum Ticker ROI Mult'].values)

    return HttpResponse(html_template.render(context, request))

@login_required(login_url="/login/")
def pages(request):
    context = {}
    # All resource paths end in .html.
    # Pick out the html file name from the url. And load that template.
    try:
        
        load_template      = request.path.split('/')[-1]
        context['segment'] = load_template
        
        html_template = loader.get_template( load_template )
        return HttpResponse(html_template.render(context, request))
        
    except template.TemplateDoesNotExist:

        html_template = loader.get_template( 'page-404.html' )
        return HttpResponse(html_template.render(context, request))

    except:
    
        html_template = loader.get_template( 'page-500.html' )
        return HttpResponse(html_template.render(context, request))
