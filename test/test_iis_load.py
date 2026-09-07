import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def request_health(url, timeout):
    started = perf_counter()
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.status, perf_counter() - started
    except HTTPError as error:
        return error.code, perf_counter() - started
    except URLError as error:
        return f"ERROR: {error.reason}", perf_counter() - started
    except TimeoutError:
        return "ERROR: timed out", perf_counter() - started


def main():
    parser = argparse.ArgumentParser(description="Send concurrent read-only requests to an IIS + ARR health endpoint.")
    parser.add_argument("--url", required=True, help="Health URL, for example http://127.0.0.1:5000/health")
    parser.add_argument("--requests", type=int, default=400, help="Total number of requests (default: 400)")
    parser.add_argument("--concurrency", type=int, default=20, help="Concurrent requests (default: 20)")
    parser.add_argument("--timeout", type=float, default=10, help="Timeout per request in seconds (default: 10)")
    args = parser.parse_args()

    if args.requests < 1 or args.concurrency < 1 or args.timeout <= 0:
        parser.error("requests, concurrency, and timeout must be positive values")

    started = perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(executor.map(lambda _: request_health(args.url, args.timeout), range(args.requests)))
    elapsed = perf_counter() - started

    statuses = Counter(status for status, _ in results)
    print(f"URL: {args.url}")
    print(f"Requests: {args.requests}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Elapsed: {elapsed:.2f}s")
    print(f"Requests/second: {args.requests / elapsed:.2f}")
    for status, count in sorted(statuses.items(), key=lambda item: str(item[0])):
        print(f"{status}: {count}")

    return 0 if all(isinstance(status, int) and 200 <= status < 300 for status in statuses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
