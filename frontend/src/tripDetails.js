export function travellersLabel(passengers = 2, withPet = false) {
  const count = Number(passengers);
  const last = count % 10;
  const teen = count % 100 >= 11 && count % 100 <= 14;
  const word = !teen && last === 1 ? 'гость' : !teen && last >= 2 && last <= 4 ? 'гостя' : 'гостей';
  return `${count} ${word}${withPet ? ' + питомец' : ''}`;
}

export function loyaltyPoints(total) {
  return Math.max(150, Math.floor((Math.max(0, total) * 15 + 500) / 1000));
}

export function partyDetails(state = {}, trip = {}) {
  const saved = trip.travellers || {};
  const ages = state.children_ages ?? saved.children_ages ?? [];
  const adults = state.adults ?? saved.adults ?? ((state.passengers ?? saved.passengers ?? 2) - ages.length);
  return { adults, children_ages: ages, passengers: adults + ages.length, withPet: state.pet_friendly ?? saved.withPet ?? false };
}

export function partyLabel(party = {}) {
  if (party.adults == null) return travellersLabel(party.passengers ?? 2, party.withPet);
  const adultWord = party.adults === 1 ? 'взрослый' : 'взрослых';
  const ages = party.children_ages || [];
  return `${party.adults} ${adultWord}${ages.length ? ` + ${ages.length} ${ages.length === 1 ? 'ребёнок' : ages.length < 5 ? 'ребёнка' : 'детей'} (${ages.map(ageLabel).join(', ')})` : ''}${party.withPet ? ' + питомец' : ''}`;
}

export function ageLabel(age) { return age === 0 ? 'до 1 года' : `${age} ${age === 1 ? 'год' : age < 5 ? 'года' : 'лет'}`; }

export function validPartyDraft(adults, ages) {
  const count = Number(adults);
  return Number.isInteger(count) && count >= 1 && count + ages.length <= 10 &&
    ages.every(age => age !== '' && Number.isInteger(Number(age)) && Number(age) >= 0 && Number(age) <= 17) &&
    ages.filter(age => Number(age) < 2).length <= count;
}
