import os
import json
import logging
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

    crawler = DigiwinCrawler(max_pages=0)

    def on_progress(pages_data, sitemap_urls, broken_links, skipped_pages, robot_parser):
        analyzer = SeoAnalyzer(pages_data, sitemap_urls, broken_links, skipped_pages, robot_parser)
        issues = analyzer.analyze()
        generate_report(issues, len(pages_data))
        logging.info(f"Intermediate report updated ({len(pages_data)} pages crawled so far)")

    pages_data, sitemap_urls, broken_links, skipped_pages, robot_parser = crawler.crawl(
        progress_callback=on_progress,
        progress_interval=10
    )

    analyzer = SeoAnalyzer(pages_data, sitemap_urls, broken_links, skipped_pages, robot_parser)
    issues = analyzer.analyze()

    with open('issues.json', 'w', encoding='utf-8') as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)

    generate_report(issues, len(pages_data))
    
if __name__ == "__main__":
    main()
