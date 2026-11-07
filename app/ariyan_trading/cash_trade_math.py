"""A016 conservative cash-trade simulation arithmetic; no execution or authority."""
import hashlib
import json
from dataclasses import replace
from decimal import Context, Decimal as D, ROUND_HALF_EVEN, localcontext

from .instruments import InstrumentSpec, ProductType
from .ledger_validation import bounded_decimal

CONTEXT = Context(prec=100, rounding=ROUND_HALF_EVEN)
BPS = D(10000)
PRICE_CONVENTION = 'QUOTE_CURRENCY_PER_ONE_QUANTITY_UNIT'


def _number(value):
    return D(bounded_decimal(value))


def _text(value):
    if value == 0:
        return '0'
    text = format(value,'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _grid(value,step):
    vn,vd = value.as_integer_ratio(); sn,sd = step.as_integer_ratio()
    return (vn*sd) % (vd*sn) == 0


def _round(value,step,*,up):
    """Exact nonnegative zero-origin step rounding using integer ratios."""
    vn,vd = value.as_integer_ratio(); sn,sd = step.as_integer_ratio()
    ticks,remainder = divmod(vn*sd,vd*sn)
    if up and remainder:
        ticks += 1
    return D(ticks)*step


def _cost(value):
    result = _number(value)
    if not 0 <= result <= 1000:
        raise ValueError('Fee and slippage must be in 0..1000 bps; rebates unsupported')
    return result


def _encoded(record):
    return json.dumps(record,sort_keys=True,separators=(',',':'),
                      ensure_ascii=True,allow_nan=False).encode('ascii')


def quote_cash_trade(spec, side, quantity, reference_price, *, cash_currency,
                     cash_step, fee_bps, slippage_bps, price_convention):
    """Model one complete cash-leg quote; not a venue fill or order admission.

    Reference price/quantity must already fit instrument grids. Adverse price
    slippage is rounded up for buys/down for sells. Posted notional is rounded
    up for buys/down for sells; fees round up, all on explicit cash_step.
    """
    with localcontext(CONTEXT):
        if type(spec) is not InstrumentSpec:
            raise ValueError('InstrumentSpec required')
        spec = replace(spec)
        if spec.product not in (ProductType.SPOT,ProductType.SHARE,ProductType.FUND_SHARE):
            raise ValueError('Only unlevered spot/share/fund-share cash arithmetic is supported')
        if (spec.contract_multiplier != 1 or type(cash_currency) is not str
                or cash_currency != spec.quote_currency or cash_currency != spec.settlement_currency):
            raise ValueError('Multiplier 1 and matching quote/settlement/cash currency required; no FX')
        if type(side) is not str or side not in ('BUY','SELL'):
            raise ValueError('Explicit BUY or SELL required')
        if type(price_convention) is not str or price_convention != PRICE_CONVENTION:
            raise ValueError('Explicit quote-currency-per-quantity-unit price convention required')
        step = _number(cash_step)
        if step <= 0:
            raise ValueError('Cash step must be positive')
        fee = _cost(fee_bps); slip = _cost(slippage_bps)
        reference,quantity = spec.validate_lattice(reference_price,quantity)
        if reference <= 0:
            raise ValueError('Cash arithmetic requires positive reference prices')
        adverse = reference*(1+slip/BPS if side=='BUY' else 1-slip/BPS)
        fill = _round(adverse,spec.price_step,up=(side=='BUY'))
        if fill <= 0:
            raise ValueError('Modeled adverse tick price is zero/dust')
        fill,quantity = spec.validate_lattice(_text(fill),quantity)
        exact_notional = quantity*fill
        notional = _round(exact_notional,step,up=(side=='BUY'))
        fee_amount = _round(notional*fee/BPS,step,up=True)
        if notional <= 0 or side=='SELL' and notional <= fee_amount:
            raise ValueError('Modeled cash proceeds are zero or consumed by fees')
        cash_delta = -(notional+fee_amount) if side=='BUY' else notional-fee_amount
        units_delta = quantity if side=='BUY' else -quantity
        record = {'version':'ARIYAN-A016-CASH-QUOTE-V1','mode':'OFFLINE_CONSERVATIVE_CASH_MATH',
            'instrument':spec.to_record(),'instrument_spec_sha256':spec.fingerprint(),
            'side':side,'cash_currency':cash_currency,'cash_step':_text(step),
            'price_convention':price_convention,'price_convention_independently_verified':False,
            'quantity':_text(quantity),'reference_price':_text(reference),'modeled_fill_price':_text(fill),
            'fee_bps':_text(fee),'slippage_bps':_text(slip),
            'exact_modeled_notional':_text(exact_notional),'posted_notional':_text(notional),
            'notional_rounding_adjustment':_text(notional-exact_notional),
            'fee':_text(fee_amount),'cash_delta':_text(cash_delta),'units_delta':_text(units_delta),
            'modeled_slippage_cost':_text(quantity*abs(fill-reference)),
            'slippage_cost_is_already_in_cash_delta':True,
            'rounding_policy':'BUY_PRICE_AND_NOTIONAL_UP_SELL_PRICE_AND_NOTIONAL_DOWN_FEES_UP',
            'venue_rules_independently_verified':False,'actual_fill_established':False,
            'order_admission_established':False,'live_authorized':False,
            'limitations':[
                'Conservative simulation convention, not an authenticated venue fee/rounding specification.',
                'No session/effective-time, depth, latency, spread feed, partial-fill or dynamic-filter checks.',
                'No minimum-notional, maximum-order, price-band, tax or non-cash fee-currency rules.',
                'No FX, borrowing, shorting, derivative margin/settlement, dividends or corporate actions.',
                'No account access, ledger posting, portfolio risk, human authority or order submission.']}
        record['quote_sha256'] = hashlib.sha256(b'ARIYAN-A016-CASH-QUOTE-V1\0'+_encoded(record)).hexdigest()
        return record


def simulate_cash_trade(spec, side, quantity, reference_price, *, opening_cash,
                        opening_units, cash_currency, cash_step, fee_bps, slippage_bps, price_convention):
    """Pure long-only, unlevered balance arithmetic; returns a new record, writes nothing.

    Existing holdings need not fit the order minimum/grid; only the traded
    quantity must. No residual/dust holdings are automatically rounded or sold.
    """
    with localcontext(CONTEXT):
        quote = quote_cash_trade(spec,side,quantity,reference_price,cash_currency=cash_currency,
            cash_step=cash_step,fee_bps=fee_bps,slippage_bps=slippage_bps,price_convention=price_convention)
        cash = _number(opening_cash); units = _number(opening_units)
        if cash < 0 or units < 0 or not _grid(cash,D(quote['cash_step'])):
            raise ValueError('Opening cash must be nonnegative/on cash grid; units must be nonnegative')
        after_cash = cash+D(quote['cash_delta'])
        after_units = units+D(quote['units_delta'])
        if after_cash < 0 or after_units < 0:
            raise ValueError('Insufficient simulated cash or holdings; borrowing/shorting unsupported')
        # Reapply input bounds to balance outputs, normalizing arithmetic trailing zeros.
        after_cash = _number(_text(after_cash)); after_units = _number(_text(after_units))
        return {'version':'ARIYAN-A016-CASH-BALANCE-SIMULATION-V1','quote':quote,
                'opening_cash':_text(cash),'opening_units':_text(units),
                'cash_after':_text(after_cash),'units_after':_text(after_units),
                'ledger_posted':False,'risk_approval_established':False,'live_authorized':False}
