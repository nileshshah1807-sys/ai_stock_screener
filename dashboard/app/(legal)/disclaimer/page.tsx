import type { Metadata } from "next";
import Link from "next/link";

import { LEGAL } from "@/lib/legal";

export const metadata: Metadata = { title: "Disclaimer & data sources" };

export default function DisclaimerPage() {
  return (
    <>
      <h1>Disclaimer &amp; data sources</h1>
      <p className="text-muted-foreground">Effective {LEGAL.effective}</p>

      <div className="mt-6 rounded-md border border-caution/40 bg-caution/5 p-4">
        <p className="mt-0! font-medium">Please read this before using {LEGAL.service}.</p>
        <p className="mt-1!">
          {LEGAL.service} is a data and research tool for education. It is not registered with SEBI
          as an Investment Adviser or Research Analyst, and nothing on it is advice or a
          recommendation. Every investment decision, and its outcome, is yours.
        </p>
      </div>

      <h2>1. Not investment advice</h2>
      <p>Nothing in the Service is, or should be read as:</p>
      <ul>
        <li>investment advice, or a recommendation to buy, sell or hold any security;</li>
        <li>a research report, a trading signal, or a target price;</li>
        <li>financial planning suited to your goals, income or risk tolerance;</li>
        <li>tax, legal or accounting advice;</li>
        <li>a promise of any return or performance.</li>
      </ul>
      <p>
        Scores, ranks and stages describe what the data showed on a given day under a fixed set
        of rules. Do not rely on them alone; do your own research and, before investing, consult a
        qualified professional.
      </p>

      <h2>2. No SEBI registration</h2>
      <p>
        We are not registered with the Securities and Exchange Board of India as an Investment
        Adviser or Research Analyst, nor with any regulator in the United States, and we do not
        provide the services that registration covers. If you want personal advice or a stock
        recommendation, consult a SEBI-registered Investment Adviser or Research Analyst; the
        register of them is published on <a href="https://www.sebi.gov.in/">SEBI&rsquo;s website</a>.
      </p>

      <h2>3. Market risk</h2>
      <p>Investments in securities are subject to market risk. In particular:</p>
      <ul>
        <li>prices can move sharply on market, economic or company news;</li>
        <li>you can lose part or all of the money you invest;</li>
        <li>no return is guaranteed;</li>
        <li>past performance, real or simulated, does not predict future results;</li>
        <li>what suits one investor can be wrong for another.</li>
      </ul>
      <p>Read all related documents carefully before investing.</p>

      <h2>4. Where the data comes from</h2>
      <ul>
        <li>
          Company disclosures filed with the stock exchanges in India (NSE and BSE): financial
          results, shareholding patterns, corporate actions and announcements.
        </li>
        <li>
          Filings with the U.S. Securities and Exchange Commission (EDGAR) for annual statements of
          U.S. companies.
        </li>
        <li>Third-party market data providers for prices, quotes and company information.</li>
        <li>
          Earnings-call transcripts and recordings published by the companies themselves.
        </li>
      </ul>

      <h2>5. Accuracy and delays</h2>
      <p>
        Prices are end-of-day unless marked live; live quotes are delayed and refreshed every few
        minutes during market hours. Filings appear after we collect and parse them, which can
        take from minutes to a day, and a scheduled update can be late or missed. Data from any
        source can be incomplete or wrong, and our calculations can contain errors. Check the
        original filing or exchange data before relying on any figure.
      </p>

      <h2>6. How artificial intelligence is used</h2>
      <p>
        Parts of the Service are produced by automated models, including AI language models:
        the reading of earnings calls (management&rsquo;s outlook and tone, and the statements
        quoted from a call) and the transcription of call recordings. These models can misread,
        omit or misattribute what was said. Treat their output as a reading of the source, not a
        statement of fact, and never as a recommendation.
      </p>

      <h2>7. Models and past performance</h2>
      <p>
        The scoring model is a research model whose out-of-sample validation is ongoing. Any
        historical or simulated figure is illustrative, does not account for every cost an
        investor would bear, and is not a guide to future results.
      </p>

      <h2>8. What the Service is for</h2>
      <p>
        {LEGAL.service} is meant to help you learn and research: how companies&rsquo; results and
        filings compare, how relative strength and price stages are measured, and how a
        rules-based score is built from the evidence. Using it to learn a method is not a
        recommendation to follow that method.
      </p>

      <h2>9. Conflicts of interest</h2>
      <p>
        The operator of {LEGAL.service} may hold, buy or sell securities that appear in the
        Service. No one is paid by a company to include, score or rank it.
      </p>

      <h2>10. Liability</h2>
      <p>
        We are not responsible for any loss arising from your use of the Service or from relying
        on its content. The full terms, including the limit on our liability, are in the{" "}
        <Link href="/terms">Terms of Service</Link>.
      </p>

      <h2>11. Your acknowledgement</h2>
      <p>
        By using {LEGAL.service} you confirm that you have read this page, that you understand the
        Service is not advice, and that you alone are responsible for your investment decisions.
      </p>

      <h2>Contact</h2>
      <p>
        Report an error in the data, or ask about this page: {LEGAL.contactEmail}.
      </p>
    </>
  );
}
