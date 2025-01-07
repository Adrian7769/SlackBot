import logging
import math
from discord_webhook import DiscordWebhook, DiscordEmbed
from alertbot.utils import config
from alertbot.alerts.base import Base
import threading
from datetime import datetime
import time

logger = logging.getLogger(__name__)

class IB_Equity_Alert(Base):
    def __init__(self, files):
        super().__init__(files=files)
        
    # ---------------------- Specific Calculations ------------------------- #
    def ib_info(self, ib_high, ib_low, ib_atr):
        logger.debug(f" IB_EQUITY | ib_info | Note: Running")
        
        ib_range = round((ib_high - ib_low), 2)
        ib_vatr = round((ib_range / ib_atr), 2)
       
        if ib_vatr > 1.1:
            ib_type = "Wide IB"
        elif ib_vatr < 0.85:
            ib_type = "Narrow IB"
        elif 0.85 <= ib_vatr <= 1.1:
            ib_type = "Average IB"
        
        return ib_range, ib_type, round((ib_vatr*100), 2)

    def slope_to_vwap(self, delta_price, scale_price=1.0, scale_time=1.0):
        logger.debug(f" IB_EQUITY | slope_to_vwap | delta_price: {delta_price} | Note: Running")
        delta_time = 0.5
        
        delta_y = delta_price * scale_price
        delta_x = delta_time * scale_time
        slope = delta_y / delta_x
        
        theta_radians = math.atan(slope)
        theta_degrees = round((math.degrees(theta_radians)), 2)
        
        if theta_degrees >= 10:
            vwap_type = 'Strong' 
        else:
            vwap_type = 'Flat'
            
        logger.debug(f" IB_EQUITY | slope_to_vwap | delta_x: {delta_price} | delta_y: {delta_y} | slope: {slope} | theta_degrees: {theta_degrees} | Note: Complete")
            
        return theta_degrees, vwap_type
        
    def exp_range_info(self, prior_close, cpl, ovn_to_ibh, ovn_to_ibl, impvol):
        logger.debug(f" IB_EQUITY | exp_range_info | Note: Running")
        
        exp_range = round(((prior_close * (impvol / 100)) * math.sqrt(1 / 252)), 2)
        exp_hi = (prior_close + exp_range)
        exp_lo = (prior_close - exp_range)
        range_used = round(((ovn_to_ibh - ovn_to_ibl) / exp_range), 2)

        if abs(range_used) >= 1:
            exhausted = "Exhausted"
        elif abs(range_used) <= 0.55:
            exhausted = "Below Avg"
        else:
            exhausted = "Nominal"

        if cpl > exp_hi:
            range_up = "Exhausted"
        else:
            range_up = round(abs((exp_hi - cpl) / (exp_range * 2) * 100), 2)

        if cpl < exp_lo:
            range_down = "Exhausted"
        else:
            range_down = round(abs((exp_lo - cpl) / (exp_range * 2) * 100), 2)
        
        return exhausted, range_used*100, range_up, range_down, exp_range

    def gap_info(self, day_open, prior_high, prior_low, exp_range):
        logger.debug(f" IB_EQUITY | gap_info | Note: Running")
        
        gap = ""
        gap_tier = ""
        gap_size = 0
        
        if day_open > prior_high:
            gap_size = round((day_open - prior_high), 2)
            gap = "Gap Up"
            
            if exp_range == 0:
                gap_tier = "Undefined"  
            else:
                gap_ratio = round((gap_size / exp_range) , 2)
                if gap_ratio <= 0.5:
                    gap_tier = "Tier 1"
                elif gap_ratio <= 0.75:
                    gap_tier = "Tier 2"
                else:
                    gap_tier = "Tier 3"
        
        elif day_open < prior_low:
            gap_size = round((prior_low - day_open), 2)
            gap = "Gap Down"
            
            if exp_range == 0:
                gap_tier = "Undefined" 
            else:
                gap_ratio = round((gap_size / exp_range) , 2)
                if gap_ratio <= 0.5:
                    gap_tier = "Tier 1"
                elif gap_ratio <= 0.75:
                    gap_tier = "Tier 2"
                else:
                    gap_tier = "Tier 3"
        
        else:
            gap = "No Gap"
            gap_tier = "Tier 0"
            gap_size = 0
        
        return gap, gap_tier, gap_size

    def posture(self, cpl, fd_vpoc, td_vpoc, exp_range):
        logger.debug(f" IB_EQUITY | posture | Note: Running")
        
        threshold = round((exp_range * 0.68), 2)

        if (abs(cpl - fd_vpoc) <= threshold) and (abs(fd_vpoc - td_vpoc) <= threshold):
            posture = "PRICE=5D=20D"
        elif (cpl > fd_vpoc + threshold) and (fd_vpoc > td_vpoc + threshold):
            posture = "PRICE^5D^20D"
        elif (cpl < fd_vpoc - threshold) and (fd_vpoc < td_vpoc - threshold):
            posture = "PRICEv5Dv20D"
        elif (abs(cpl - fd_vpoc) <= threshold) and (fd_vpoc > td_vpoc + threshold):
            posture = "PRICE=5D^20D"
        elif (cpl > fd_vpoc + threshold) and (abs(fd_vpoc - td_vpoc) <= threshold):
            posture = "PRICE^5D=20D"
        elif (cpl < fd_vpoc - threshold) and (abs(fd_vpoc - td_vpoc) <= threshold):
            posture = "PRICEv5D=20D"
        elif (abs(cpl - fd_vpoc) <= threshold) and (fd_vpoc < td_vpoc - threshold):
            posture = "PRICE=5Dv20D"
        elif (cpl > fd_vpoc + threshold) and (fd_vpoc < td_vpoc - threshold):
            posture = "PRICE^5Dv20D"
        elif (cpl < fd_vpoc - threshold) and (fd_vpoc > td_vpoc + threshold):
            posture = "PRICEv5D^20D"
        else:
            posture = "Other"

        return posture
        
    def open_type(self, a_high, a_low, b_high, b_low, day_open, orh, orl, prior_high, prior_low):
        logger.debug(f" IB_EQUITY | open_type | Note: Running")
        
        a_period_mid = round(((a_high + a_low) / 2), 2)
        a_period_range = (a_high - a_low)
        overlap = max(0, min(max(a_high, b_high), prior_high) - max(min(a_low, b_low), prior_low))
        total_range = max(a_high, b_high) - min(a_low, b_low)

        if (abs(day_open - a_high) <= 0.025 * a_period_range) and (b_high < a_period_mid):
            open_type = "OD v"
        elif (abs(day_open - a_low) <= 0.025 * a_period_range) and (b_low > a_period_mid):
            open_type = "OD ^"
        elif (day_open > a_period_mid) and (b_high < a_period_mid):
            open_type = "OTD v"
        elif (day_open < a_period_mid) and (b_low > a_period_mid):
            open_type = "OTD ^"
        elif (day_open > a_period_mid) and (b_low > a_period_mid) and (b_high > orh):
            open_type = "ORR ^"
        elif (day_open < a_period_mid) and (b_high < a_period_mid) and (b_low < orl):
            open_type = "ORR v"
        elif overlap >= 0.5 * total_range:
            open_type = "OAIR"
        elif (overlap < 0.5 * total_range) and (day_open >= prior_high):
            open_type = "OAOR ^"
        elif (overlap < 0.5 * total_range) and (day_open <= prior_low):
            open_type = "OAOR v"
        else:
            open_type = "Other"

        return open_type
    # ---------------------- Alert Preparation ------------------------- #
    def send_alert(self):
        threads = []
        for product_name in ['ES', 'NQ', 'RTY']:
            thread = threading.Thread(target=self.process_product, args=(product_name,))
            thread.start()
            threads.append(thread)
            time.sleep(1)

        # Optionally wait for all threads to complete
        for thread in threads:
            thread.join()

    def process_product(self, product_name):
        try:
            variables = self.fetch_latest_variables(product_name)
            if not variables:
                logger.error(f" IB_EQUITY | process_product | Product: {product_name} |  Note: No data available ")
                return
            
            # Variables (Round All Variables) 
            ib_atr = round(variables.get(f'{product_name}_IB_ATR'), 2)
            ib_high = round(variables.get(f'{product_name}_IB_HIGH'), 2)
            ib_low = round(variables.get(f'{product_name}_IB_LOW'), 2)
            prior_close = round(variables.get(f'{product_name}_PRIOR_CLOSE'), 2)
            day_open = round(variables.get(f'{product_name}_DAY_OPEN'), 2)
            prior_high = round(variables.get(f'{product_name}_PRIOR_HIGH'), 2)
            prior_low = round(variables.get(f'{product_name}_PRIOR_LOW'), 2)
            cpl = round(variables.get(f'{product_name}_CPL'), 2)
            fd_vpoc = round(variables.get(f'{product_name}_5D_VPOC'), 2)
            td_vpoc = round(variables.get(f'{product_name}_20D_VPOC'), 2)
            ovn_to_ibh = round(variables.get(f'{product_name}_OVNTOIB_HI'), 2)
            ovn_to_ibl = round(variables.get(f'{product_name}_OVNTOIB_LO'), 2)
            a_high = round(variables.get(f'{product_name}_A_HIGH'), 2)
            a_low = round(variables.get(f'{product_name}_A_LOW'), 2)
            b_high = round(variables.get(f'{product_name}_B_HIGH'), 2)
            b_low = round(variables.get(f'{product_name}_B_LOW'), 2)
            orh = round(variables.get(f'{product_name}_ORH'), 2)
            orl = round(variables.get(f'{product_name}_ORL'), 2)
            rvol = round(variables.get(f'{product_name}_CUMULATIVE_RVOL'), 2)
            overnight_high = round(variables.get(f'{product_name}_OVNH'), 2)
            overnight_low = round(variables.get(f'{product_name}_OVNL'), 2)
            day_high = round(variables.get(f'{product_name}_DAY_HIGH'), 2)
            day_low = round(variables.get(f'{product_name}_DAY_LOW'), 2) 
            eth_vwap = variables.get(f'{product_name}_ETH_VWAP')
            eth_vwap_pt = variables.get(f'{product_name}_ETH_VWAP_P2') 
            delta_price = abs(eth_vwap - eth_vwap_pt)

            # Implied volatility specific to the product
            if product_name == 'ES':
                impvol = config.es_impvol
            elif product_name == 'NQ':
                impvol = config.nq_impvol
            elif product_name == 'RTY':
                impvol = config.rty_impvol
            else:
                raise ValueError(f" IB_EQUITY | process_product | Note: {product_name}")
            
            color = self.product_color.get(product_name)
            current_time = datetime.now(self.est).strftime('%H:%M:%S')
            
            # Calculations
            ib_range, ib_type, ib_vatr = self.ib_info(
                ib_high, ib_low, ib_atr
                )
            exhausted, range_used, range_up, range_down, exp_range = self.exp_range_info(
                prior_close, cpl, ovn_to_ibh, ovn_to_ibl, impvol
                )
            gap, gap_tier, gap_size = self.gap_info(
                day_open, prior_high, prior_low, exp_range
                )
            posture = self.posture(
                cpl, fd_vpoc, td_vpoc, exp_range
                )
            open_type = self.open_type(
                a_high, a_low, b_high, b_low, day_open, orh, orl, prior_high, prior_low
                )
            vwap_slope, vwap_type = self.slope_to_vwap(
                delta_price, scale_time=1.0, scale_price=1.0
                )
            
            # Build the Discord Embed
            try:
                embed_title = f":large_{color}_square: **{product_name} - Context - IB Check-In** :loudspeaker:"
                embed = DiscordEmbed(
                    title=embed_title,
                    description=(
                        f"**Open Type**: _{open_type}_\n"
                        f"**{ib_type}**: _{ib_range}p_ = _{round(ib_vatr, 2)}%_ of Avg\n"
                        f"**Vwap {vwap_type}**: _{vwap_slope}°_\n"
                    ),
                    color=self.get_color()
                )
                embed.set_timestamp()  # Automatically sets the timestamp to current time

                # Add Gap Information if applicable
                if gap != 'No Gap':
                    embed.add_embed_field(name=f":warning: {gap}", value=f"_Size_: {gap_size} | _Tier_: {gap_tier}", inline=False)
                
                # Add Overnight Stat if applicable
                if day_high < overnight_high and day_low > overnight_low:
                    embed.add_embed_field(name=":night_with_stars: Overnight Stat", value="_In Play_", inline=False)
                
                # Add Rvol and Posture
                embed.add_embed_field(name=":chart_with_upwards_trend: Rvol", value=f"_{rvol}%_", inline=True)
                embed.add_embed_field(name=":balance_scale: Current Posture", value=f"_{posture}_", inline=True)

                # Expected Range Section
                embed.add_embed_field(name=":bar_chart: Expected Range", value=(
                    f"**Rng Used**: _{exhausted}_ | _{range_used}%_ Used\n"
                    f"**Range Left Up**: _{range_up}{'' if range_up == 'Exhausted' else '%'}_\n"
                    f"**Range Left Down**: _{range_down}{'' if range_down == 'Exhausted' else '%'}_"
                ), inline=False)
                
                # Alert Time
                embed.add_embed_field(name=":alarm_clock: Alert Time", value=f"_{current_time}_ EST", inline=False)

                # Send the embed with the webhook
                webhook_url = self.discord_webhooks_playbook.get(product_name)
                if webhook_url:
                    webhook = DiscordWebhook(url=webhook_url, username="IB Equity Alert", content=f"Alert for {product_name}")
                    webhook.add_embed(embed)
                    response = webhook.execute()
                    if response.status_code == 200 or response.status_code == 204:
                        logger.info(f" IB_EQUITY | process_product | Note: Message sent to Discord webhook for {product_name}")
                    else:
                        logger.error(f" IB_EQUITY | process_product | Note: Failed to send message to Discord webhook for {product_name} | Status Code: {response.status_code}")
                else:
                    logger.error(f" IB_EQUITY | process_product | Note: No Discord webhook configured for {product_name}")
            except Exception as e:
                logger.error(f" IB_EQUITY | process_product | Product: {product_name} | Error sending Discord message: {e}")
        except Exception as e:
            logger.error(f" IB_EQUITY | process_product | Product: {product_name} | Error processing: {e}")