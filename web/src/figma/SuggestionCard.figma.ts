// url=https://www.figma.com/design/I0dtgDaYeGWv360bEOOCK4/BoardNotes-Prototype?node-id=20-215
// source=web/src/components/SuggestionCard.tsx
// component=SuggestionCard
import figma from 'figma'
const instance = figma.selectedInstance

// The code card takes a whole Suggestion (contract type); author, avatar, upvote and AI verdict all come from it.
const author = instance.getString('Author')
const proposed = instance.getString('Proposed fix')

export default {
  example: figma.code`{/* ${author}: "${proposed}" */}
<SuggestionCard suggestion={suggestion} onVote={() => vote(suggestion.id)} />`,
  imports: ['import { SuggestionCard } from "@/components/SuggestionCard"'],
  id: 'suggestion-card',
  metadata: { nestable: false },
}
