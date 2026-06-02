import os
import json
import logging
import subprocess
import time
import sys
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from crawler import DigiwinCrawler
from analyzer import SeoAnalyzer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def generate_report(issues, total_pages):
    # Group issues by type
    issues_by_type = {}
    summary = {}
    for issue in issues:
        t = issue["type"]
        if t not in issues_by_type:
            issues_by_type[t] = []
            summary[t] = 0
        issues_by_type[t].append(issue)
        summary[t] += 1
        
    # Sort issues_by_type by count descending
    summary_sorted = dict(sorted(summary.items(), key=lambda item: item[1], reverse=True))

    env = Environment(loader=FileSystemLoader('.'))
    try:
        template = env.get_template('template.html')
    except Exception as e:
        logging.error(f"Failed to load template.html: {e}")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    year = datetime.now().strftime("%Y")
    
    html_content = template.render(
        timestamp=now,
        year=year,
        total_pages=total_pages,
        total_issues=len(issues),
        summary=summary_sorted,
        issues_by_type=issues_by_type
    )

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    logging.info("Report generated successfully: index.html")

def main():
    logging.info("Starting weekly SEO check...")

    state_file = 'crawler_state.json'
    completed = False

    # Check weekly reset based on the timestamp stored INSIDE the state file.
    # File mtime is unreliable here because `git checkout` resets it to "now",
    # which would prevent the weekly crawl from ever restarting.
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                saved_ts = json.load(f).get("timestamp", 0)
            age_days = (time.time() - saved_ts) / (24 * 3600)
            if age_days > 3:
                logging.info(f"State is {age_days:.1f} days old (> 3 days). Starting fresh weekly crawl.")
                os.remove(state_file)
        except Exception as e:
            logging.error(f"Failed to check/remove old state file: {e}")

    crawler = DigiwinCrawler(max_pages=0)

    # Load state if it still exists after the freshness check
    if os.path.exists(state_file):
        logging.info(f"Found existing state file: {state_file}")
        state = crawler.load_state(state_file)
        if state and state.get("completed", False):
            logging.info("Crawl already completed this week. Exiting.")
            sys.exit(0)

    def on_progress(pages_data, sitemap_urls, broken_links, skipped_pages, robot_parser):
        # Save current state first
        crawler.save_state(state_file, completed=False)

        analyzer = SeoAnalyzer(pages_data, sitemap_urls, broken_links, skipped_pages, robot_parser)
        issues = analyzer.analyze()
        generate_report(issues, len(pages_data))
        logging.info(f"Intermediate report updated ({len(pages_data)} pages crawled so far)")
        try:
            subprocess.run(["git", "add", "index.html", state_file], check=True)
            result = subprocess.run(
                ["git", "diff", "--staged", "--quiet"],
                capture_output=True
            )
            if result.returncode != 0:
                subprocess.run(["git", "commit", "-m", f"Progress: {len(pages_data)} pages crawled (Queue: {len(crawler.queue)})"], check=True)
                subprocess.run(["git", "push"], check=True)
                logging.info(f"Pushed intermediate index.html and state at {len(pages_data)} pages")
        except subprocess.CalledProcessError as e:
            logging.warning(f"Git push skipped (not in CI or git error): {e}")

    # Run crawl (max 5 hours = 18000 seconds)
    pages_data, sitemap_urls, broken_links, skipped_pages, robot_parser = crawler.crawl(
        progress_callback=on_progress,
        progress_interval=200,
        max_duration_seconds=18000
    )

    # Determine if fully completed
    completed = len(crawler.queue) == 0
    crawler.save_state(state_file, completed=completed)

    analyzer = SeoAnalyzer(pages_data, sitemap_urls, broken_links, skipped_pages, robot_parser)
    issues = analyzer.analyze()

    with open('issues.json', 'w', encoding='utf-8') as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)

    generate_report(issues, len(pages_data))
    
if __name__ == "__main__":
    main()
