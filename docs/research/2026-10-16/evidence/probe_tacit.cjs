// Disposable probe of upstream scoring, not X-Agent product code.
const path = require('node:path');
const sdk = require(path.resolve(__dirname, '../../../../../tacit/packages/sdk-ts/dist/index.js'));
const scorer = new sdk.MatchScorer();
const card = did => ({
  agent: {did},
  authenticity: {score: 60},
  preferences: {languages: ['en'], introductionStyle: 'progressive'},
});
const intent = (did, role) => new sdk.IntentBuilder(did)
  .type('introduction').domain('professional').seeking({role}).build();
const cases = [];
for (const role of ['co-founder', 'unrelated-role']) {
  const result = scorer.score({
    initiator: {card: card('did:a'), intent: intent('did:a', 'co-founder')},
    responder: {card: card('did:b'), intent: intent('did:b', role)},
  });
  const b = result.score.breakdown;
  const weighted = b.intentAlignment * .3 + b.domainFit * .25 +
    b.authenticityCompatibility * .2 + b.preferenceMatch * .15 + b.timingFit * .1;
  cases.push({role, weighted, expectedRoundedPercentage: Math.round(weighted * 100),
    actual: result.score.overall});
}
if (!cases.every(c => c.actual === Math.round(c.weighted) * 100)) throw Error('unexpected result');
if (!cases.some(c => c.actual !== c.expectedRoundedPercentage)) throw Error('not reproduced');
console.log(JSON.stringify({probe: 'upstream rounding defect reproduced', cases}, null, 2));
