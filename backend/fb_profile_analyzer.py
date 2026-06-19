import json
import os
from datetime import datetime
import matplotlib.pyplot as plt
import pandas as pd
from dotenv import load_dotenv
from colorama import Fore, init

init(autoreset=True)
load_dotenv()

DATA_DIR = os.path.join(os.getcwd(), "data_fb_profiles")


class FBProfileAnalyzer:
    def __init__(self):
        self.data_dir = DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)

        self.plot_single_figsize = (12, 10)
        self.plot_comparison_figsize = (16, 5)
        self.plot_dpi = 100

    def list_tracked_profiles(self):
        """List semua profile FB yang sedang di-track."""
        users = set()
        if os.path.exists(self.data_dir):
            for file in os.listdir(self.data_dir):
                if file.endswith('_data.json'):
                    users.add(file.replace('_data.json', ''))
        users = sorted(list(users))

        if not users:
            print("\nTidak ada profile FB yang sedang di-track")
            return users

        print("\nDAFTAR PROFILE FB YANG SEDANG DI-TRACK:\n")
        print("=" * 60)
        for i, user in enumerate(users, 1):
            filepath = os.path.join(self.data_dir, f"{user}_data.json")
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                latest = data[-1]
                print(f"{i}. {user}")
                print(f"   Name:      {latest.get('name', 'N/A')}")
                print(f"   Followers: {latest.get('followers', 0):,}")
                print(f"   Likes:     {latest.get('likes', 0):,}")
                print(f"   Posts:     {latest.get('posts', 0):,}")
                print(f"   Category:  {latest.get('category', 'N/A')}")
                print(f"   Bio:       {latest.get('bio', '')[:50]}...")
                print(f"   Last Updated: {latest.get('timestamp', 'N/A')}")
                print("-" * 60)

        return users

    def _parse_timestamp_safe(self, timestamp_str):
        """Parse timestamp dengan handle multiple formats."""
        if not timestamp_str:
            return None
        
        if '.' in timestamp_str:
            timestamp_str = timestamp_str.split('.')[0]
        
        timestamp_str = timestamp_str.replace('T', ' ')
        
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%Y-%m-%d',
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(timestamp_str, fmt)
            except ValueError:
                continue
        
        try:
            return pd.to_datetime(timestamp_str)
        except:
            return None

    def plot_single_profile_growth(self, username):
        """Plot growth untuk single FB profile."""
        username = username.lstrip('@')
        
        filepath = os.path.join(self.data_dir, f"{username}_data.json")
        if not os.path.exists(filepath):
            print(f"\nData tidak ditemukan untuk {username}")
            print(f"Gunakan scraper dulu: python fb_profile_scraper.py")
            return

        with open(filepath, 'r', encoding='utf-8') as f:
            history = json.load(f)

        if not history or len(history) < 2:
            print(f"\nData tidak cukup untuk {username} (minimal 2 data points)")
            print(f"Saat ini hanya ada {len(history)} data point.")
            return

        # Parse timestamp manual
        parsed_data = []
        for item in history:
            ts = self._parse_timestamp_safe(item.get('timestamp', ''))
            if ts:
                parsed_data.append({
                    'timestamp': ts,
                    'followers': item.get('followers', 0) or item.get('likes', 0),
                    'likes': item.get('likes', 0),
                    'posts': item.get('posts', 0),
                })

        if len(parsed_data) < 2:
            print(f"\nData valid tidak cukup setelah parsing timestamp.")
            return

        df = pd.DataFrame(parsed_data)
        df = df.sort_values('timestamp')

        fig, axes = plt.subplots(3, 1, figsize=self.plot_single_figsize)
        fig.suptitle(f'FB Growth Analysis: {username}', fontsize=16, fontweight='bold')

        # Plot 1: Followers/Likes
        axes[0].plot(df['timestamp'], df['followers'], marker='o', color='#1877F2', linewidth=2, markersize=6)
        axes[0].set_title('Followers/Likes Growth', fontsize=12, fontweight='bold')
        axes[0].set_ylabel('Count')
        axes[0].grid(True, alpha=0.3)
        axes[0].yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x/1000)}K' if x >= 1000 else f'{int(x)}'))

        # Plot 2: Likes (terpisah kalau ada data likes)
        if df['likes'].sum() > 0 and not (df['likes'] == df['followers']).all():
            axes[1].plot(df['timestamp'], df['likes'], marker='s', color='#42B72A', linewidth=2, markersize=6)
            axes[1].set_title('Page Likes Growth', fontsize=12, fontweight='bold')
        else:
            axes[1].plot(df['timestamp'], df['followers'], marker='s', color='#42B72A', linewidth=2, markersize=6)
            axes[1].set_title('Followers Growth (Alt)', fontsize=12, fontweight='bold')
        axes[1].set_ylabel('Count')
        axes[1].grid(True, alpha=0.3)
        axes[1].yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x/1000)}K' if x >= 1000 else f'{int(x)}'))

        # Plot 3: Posts
        axes[2].plot(df['timestamp'], df['posts'], marker='^', color='#F7B928', linewidth=2, markersize=6)
        axes[2].set_title('Posts Count', fontsize=12, fontweight='bold')
        axes[2].set_ylabel('Posts')
        axes[2].set_xlabel('Date')
        axes[2].grid(True, alpha=0.3)

        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.show()

        print(f"\nSTATISTIK {username}:")
        print("=" * 60)
        print(f"Followers/Likes: {df['followers'].iloc[0]:,} → {df['followers'].iloc[-1]:,} (+{df['followers'].iloc[-1] - df['followers'].iloc[0]:,})")
        print(f"Posts: {df['posts'].iloc[0]:,} → {df['posts'].iloc[-1]:,} (+{df['posts'].iloc[-1] - df['posts'].iloc[0]:,})")
        print("=" * 60)

    def plot_comparison(self, usernames):
        """Plot comparison untuk multiple FB profiles."""
        if len(usernames) < 2:
            print("Minimal 2 profile untuk comparison")
            return

        fig, axes = plt.subplots(1, 3, figsize=self.plot_comparison_figsize)
        fig.suptitle('FB Comparison Growth Analysis', fontsize=16, fontweight='bold')

        colors = ['#1877F2', '#42B72A', '#F7B928', '#E0245E', '#794BC4', '#1B2331']

        for idx, username in enumerate(usernames):
            username = username.lstrip('@')
            
            filepath = os.path.join(self.data_dir, f"{username}_data.json")
            if not os.path.exists(filepath):
                print(f"No data for {username}")
                continue

            with open(filepath, 'r', encoding='utf-8') as f:
                history = json.load(f)

            if not history:
                print(f"No data for {username}")
                continue

            parsed_data = []
            for item in history:
                ts = self._parse_timestamp_safe(item.get('timestamp', ''))
                if ts:
                    parsed_data.append({
                        'timestamp': ts,
                        'followers': item.get('followers', 0) or item.get('likes', 0),
                        'posts': item.get('posts', 0),
                    })

            if len(parsed_data) < 2:
                print(f"Data tidak cukup untuk {username}")
                continue

            df = pd.DataFrame(parsed_data)
            df = df.sort_values('timestamp')

            color = colors[idx % len(colors)]

            axes[0].plot(df['timestamp'], df['followers'], marker='o', label=username, color=color, linewidth=2)
            axes[1].plot(df['timestamp'], df['followers'], marker='s', label=username, color=color, linewidth=2)
            axes[2].plot(df['timestamp'], df['posts'], marker='^', label=username, color=color, linewidth=2)

        axes[0].set_title('Followers/Likes Comparison', fontsize=12, fontweight='bold')
        axes[0].set_ylabel('Count')
        axes[0].grid(True, alpha=0.3)
        axes[0].legend(loc='best')

        axes[1].set_title('Followers Growth Comparison', fontsize=12, fontweight='bold')
        axes[1].set_ylabel('Count')
        axes[1].grid(True, alpha=0.3)
        axes[1].legend(loc='best')

        axes[2].set_title('Posts Comparison', fontsize=12, fontweight='bold')
        axes[2].set_ylabel('Posts')
        axes[2].grid(True, alpha=0.3)
        axes[2].legend(loc='best')

        for ax in axes:
            ax.tick_params(axis='x', rotation=45)

        plt.tight_layout()
        plt.show()

        print(f"\nTABEL PERBANDINGAN FB PROFILES:")
        print("=" * 80)
        print(f"{'Profile':<<20} {'Followers/Likes':<<20} {'Posts':<<15}")
        print("-" * 80)

        for username in usernames:
            username = username.lstrip('@')
            filepath = os.path.join(self.data_dir, f"{username}_data.json")
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    if history:
                        latest = history[-1]
                        followers = latest.get('followers', 0) or latest.get('likes', 0)
                        print(f"{username:<19} {followers:<<20,} {latest.get('posts', 0):<<15,}")

        print("=" * 80)

    def interactive_menu(self):
        """Interactive menu untuk FB profile analysis."""
        while True:
            print("\n")
            print("=" * 58)
            print(" " * 15 + "FB PROFILE GROWTH ANALYZER")
            print("=" * 58)
            print("\n1. List Tracked Profiles")
            print("2. Plot Single Profile Growth")
            print("3. Plot Comparison (Multiple Profiles)")
            print("4. Exit")
            print("\n" + "=" * 60)

            choice = input("Pilih opsi (1-4): ").strip()

            if choice == '1':
                self.list_tracked_profiles()
            elif choice == '2':
                username = input("Masukkan username/profile (contoh: prabowo): ").strip()
                if username:
                    self.plot_single_profile_growth(username)
                else:
                    print("Username tidak boleh kosong")
            elif choice == '3':
                users_input = input("Masukkan profiles (pisahkan dengan koma): ").strip()
                if users_input:
                    usernames = [u.strip() for u in users_input.split(',')]
                    self.plot_comparison(usernames)
                else:
                    print("Minimal 1 profile")
            elif choice == '4':
                print("\nTerima kasih! Sampai jumpa...")
                break
            else:
                print("Opsi tidak valid, silakan coba lagi")


if __name__ == '__main__':
    analyzer = FBProfileAnalyzer()
    analyzer.interactive_menu()