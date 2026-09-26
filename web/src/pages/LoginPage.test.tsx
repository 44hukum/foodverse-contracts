import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { session } from '../auth/session';
import { MOCK_ADMIN_EMAIL, MOCK_ADMIN_PASSWORD } from '../mocks/data';
import { renderApp } from '../test/utils';

describe('LoginPage', () => {
  it('redirects unauthenticated visitors from admin pages to the login form', async () => {
    renderApp('/contracts', { authed: false });
    expect(await screen.findByRole('heading', { name: 'Foodverse Contracts' })).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
  });

  it('shows the API message on wrong credentials and keeps the session empty', async () => {
    const user = userEvent.setup();
    renderApp('/login', { authed: false });
    await user.type(screen.getByLabelText('Email'), MOCK_ADMIN_EMAIL);
    await user.type(screen.getByLabelText('Password'), 'wrong-password-value');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Email or password is incorrect.');
    expect(session.get()).toBeNull();
  });

  it('asks for both fields before calling the API', async () => {
    const user = userEvent.setup();
    renderApp('/login', { authed: false });
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter your email and password.');
  });

  it('logs in, stores the session in memory only, and lands on the contract list', async () => {
    const user = userEvent.setup();
    renderApp('/login', { authed: false });
    await user.type(screen.getByLabelText('Email'), MOCK_ADMIN_EMAIL);
    await user.type(screen.getByLabelText('Password'), MOCK_ADMIN_PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('heading', { name: 'Contracts' })).toBeInTheDocument();
    expect(session.get()?.admin.email).toBe(MOCK_ADMIN_EMAIL);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it('returns to the page the admin was trying to open', async () => {
    const user = userEvent.setup();
    renderApp('/contracts/new', { authed: false });
    await user.type(await screen.findByLabelText('Email'), MOCK_ADMIN_EMAIL);
    await user.type(screen.getByLabelText('Password'), MOCK_ADMIN_PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'New contract' })).toBeInTheDocument();
  });

  it('logs out from the header and returns to the login form', async () => {
    const user = userEvent.setup();
    renderApp('/contracts');
    await screen.findByRole('heading', { name: 'Contracts' });
    await user.click(screen.getByRole('button', { name: 'Log out' }));
    expect(await screen.findByLabelText('Password')).toBeInTheDocument();
    expect(session.get()).toBeNull();
  });
});
