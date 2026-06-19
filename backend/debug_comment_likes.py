"""
Debug script to test comment like extraction from Facebook DOM.
Run this while on a Facebook post page to see the actual DOM structure.
"""
import json
import sys
import os

# Simple test: simulate what the JS would do
test_html_snippet = """
<div aria-label="Suka" class="x1i10hfl x1qjc9v5 xjbqb8w xjqpnuy xc5r6h4 xqeqjp1 x1phubyo x13fuv20 x18b5jzi x1q0q8m5 x1t7ytsu x972fbf x10w94by x1qhh985 x14e42zd x9f619 x1ypdohk xdl72j9 x2lah0s x3ct3a4 xdj266r x14z9mp xat24cr x1lziwak x2lwn1j xeuugli xexx8yu xyri2b x18d9i69 x1c1uobl x1n2onr6 x16tdsg8 x1hl2dhg x1ja2u2z x1t137rt x1fmog5m xu25z0z x140muxe xo1y3bh x3nfvp2 x1q0g3np x87ps6o x1lku1pv x1a2a7pz x5ve5x3" role="button" tabindex="0">
    <div class="x9f619 x1ja2u2z x2lah0s x1n2onr6 xl56j7k xozqiw3 x1q0g3np xpdmqnj x1g0dm76 x18d9i69 xexx8yu x1lxpwgx x165d6jo x4cne27 xifccgj x6s0dn4 x78zum5 xn3w4p2 xuxw1ft">
        <div class="x9f619 x1n2onr6 x1ja2u2z x78zum5 xdt5ytf x2lah0s x193iq5w xeuugli x11lfxj5 x135b78x x10b6aqq x1yrsyyn">
            <span class="x3nfvp2"><i data-visualcompletion="css-img" class="x15mokao x1ga7v0g x16uus16 xbiv7yw x1b0d499 x1d69dk1" style="background-image: url("..."); background-position: 0px -441px; background-size: auto; width: 20px; height: 20px; background-repeat: no-repeat; display: inline-block;"></i></span>
            <div data-ad-rendering-role="like_button"></div>
        </div>
        <div class="x9f619 x1n2onr6 x1ja2u2z x78zum5 xdt5ytf x2lah0s x193iq5w xeuugli x11lfxj5 x135b78x x10b6aqq x1yrsyyn">
            <span class="x193iq5w xeuugli x13faqbe x1vvkbs x1xmvt09 x1lliihq x1s928wv xhkezso x1gmr53x x1cpjm7i x1fgarty x1943h6x x4zkp8e x676frb x1nxh6w3 x1sibtaa x1s688f xi81zsa" dir="auto">970</span>
        </div>
    </div>
</div>
"""

print("Testing comment like extraction logic...")
print("=" * 60)

# Test 1: Check if aria-label contains "Suka" or "Like"
print("\n1. Testing aria-label selector:")
print("   Looking for: [aria-label*='Suka'], [aria-label*='Like']")

# Test 2: Check the inner text of the span containing the number
print("\n2. Testing inner text extraction:")
print("   Looking for span[dir='auto'] with number inside like button")

# Test 3: Check parent traversal
print("\n3. Testing parent traversal:")
print("   From like button, find parent, then find span with number")

# The key insight from the HTML:
# - The like button has aria-label="Suka" 
# - Inside it, there's a div with class containing the number span
# - The number is in: span[dir="auto"] with text like "970" or "2,3 rb"

print("\n" + "=" * 60)
print("SOLUTION: Comment likes are in a SEPARATE span inside the like button")
print("The structure is:")
print("  button[aria-label='Suka'] > div > span[dir='auto'] = '970'")
print("\nWe need to:")
print("1. Find the like button (aria-label contains 'Suka' or 'Like')")
print("2. Look for span[dir='auto'] INSIDE that button")
print("3. Parse the number from that span")
print("=" * 60)