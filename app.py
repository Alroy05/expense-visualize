import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Page configuration
st.set_page_config(
    page_title="Expense Visualizer",
    page_icon="💰",
    layout="wide"
)

# Custom styling
st.markdown("""
    <style>
    .main {
        padding: 2rem;
    }
    .stApp {
        background: #000000;
    }
    .upload-section {
        background: rgba(255, 255, 255, 0.95);
        padding: 2rem;
        border-radius: 1rem;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
    }
    h1 {
        color: white;
        font-family: 'Inter', sans-serif;
        font-weight: 700;
    }
    </style>
""", unsafe_allow_html=True)

# Title
st.title("💰 Expense Visualizer")
st.markdown("### Upload your Excel file to visualize your expenses")

# File uploader
uploaded_file = st.file_uploader(
    "Choose an Excel or CSV file",
    type=['xlsx', 'xls', 'csv'],
    help="Upload an Excel or CSV file containing your expense data"
)

if uploaded_file is not None:
    try:
        # Read the file based on its extension
        file_extension = uploaded_file.name.split('.')[-1].lower()
        if file_extension == 'csv':
            df = pd.read_csv(uploaded_file)
        else:  # xlsx or xls
            df = pd.read_excel(uploaded_file)
        
        # Normalize column names - strip whitespace
        df.columns = df.columns.str.strip()
        
        # Find the amount column (could be 'From Amount', 'From Amc', etc.)
        amount_col = None
        for col in df.columns:
            if 'from' in col.lower() and ('amount' in col.lower() or 'amc' in col.lower() or 'amt' in col.lower()):
                amount_col = col
                break
        
        # Check if required columns exist
        required_columns = ['Type', 'To']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            st.error(f"❌ Missing required columns: {', '.join(missing_columns)}")
            st.info(f"📋 **Columns found in your file:** {', '.join(df.columns.tolist())}")
            st.warning("Please make sure your file has columns: Type, To, and an amount column")
        elif amount_col is None:
            st.error("❌ Could not find an amount column (expected 'From Amount' or similar)")
            st.info(f"📋 **Columns found in your file:** {', '.join(df.columns.tolist())}")
        else:
            # Filter for Expense type only
            expense_df = df[df['Type'].str.strip() == 'Expense'].copy()
            
            # Account filter chips at the top
            if 'From' in expense_df.columns:
                st.markdown("### 💳 Filter by Account")
                
                all_accounts = sorted(expense_df['From'].unique().tolist())
                
                # Create session state for selected account if not exists
                if 'selected_account' not in st.session_state:
                    st.session_state.selected_account = 'All Accounts'
                
                # Create chips using columns
                cols = st.columns(min(len(all_accounts) + 1, 8))  # Limit to 8 columns per row
                
                # All Accounts chip
                with cols[0]:
                    if st.button(
                        "🏦 All Accounts",
                        key="chip_all",
                        use_container_width=True,
                        type="primary" if st.session_state.selected_account == 'All Accounts' else "secondary"
                    ):
                        st.session_state.selected_account = 'All Accounts'
                        st.rerun()
                
                # Individual account chips
                for idx, account in enumerate(all_accounts[:7], 1):  # Show first 7 accounts
                    if idx < len(cols):
                        with cols[idx]:
                            is_selected = st.session_state.selected_account == account
                            if st.button(
                                f"{'✓ ' if is_selected else ''}{account}",
                                key=f"chip_{account}",
                                use_container_width=True,
                                type="primary" if is_selected else "secondary"
                            ):
                                st.session_state.selected_account = account
                                st.rerun()
                
                # If more than 7 accounts, show dropdown for the rest
                if len(all_accounts) > 7:
                    remaining_accounts = all_accounts[7:]
                    selected_from_dropdown = st.selectbox(
                        "More accounts:",
                        options=[''] + remaining_accounts,
                        index=0,
                        key="more_accounts_dropdown"
                    )
                    if selected_from_dropdown:
                        st.session_state.selected_account = selected_from_dropdown
                        st.rerun()
                
                st.markdown("---")
                
                # Apply filter
                selected_account = st.session_state.selected_account
                if selected_account != 'All Accounts':
                    expense_df = expense_df[expense_df['From'] == selected_account].copy()
            else:
                selected_account = 'All Accounts'
        
            if len(expense_df) == 0:
                st.warning("⚠️ No expenses found in the uploaded file!")
            else:
                # Extract Category from 'To' column and Amount from the detected amount column
                expense_df['Category'] = expense_df['To']
                expense_df['Amount'] = pd.to_numeric(expense_df[amount_col], errors='coerce')
                
                # Remove rows with NaN amounts
                expense_df = expense_df.dropna(subset=['Amount'])
                
                # Add date processing if Date column exists
                if 'Date' in expense_df.columns:
                    expense_df['Date'] = pd.to_datetime(expense_df['Date'], errors='coerce')
                
                # Calculate average daily expense
                avg_daily_expense = 0
                if 'Date' in expense_df.columns and expense_df['Date'].notna().any():
                    date_range = (expense_df['Date'].max() - expense_df['Date'].min()).days
                    if date_range > 0:
                        avg_daily_expense = expense_df['Amount'].sum() / date_range
                    else:
                        avg_daily_expense = expense_df['Amount'].sum()
                
                # Summary statistics
                st.markdown("---")
                col1, col2, col3, col4, col5 = st.columns(5)
                
                with col1:
                    st.metric(
                        label="💸 Total Expenses",
                        value=f"₹{expense_df['Amount'].sum():,.2f}"
                    )
                
                with col2:
                    st.metric(
                        label="📊 Transactions",
                        value=f"{len(expense_df)}"
                    )
                
                with col3:
                    st.metric(
                        label="📈 Avg Expense",
                        value=f"₹{expense_df['Amount'].mean():,.2f}"
                    )
                
                with col4:
                    st.metric(
                        label="📅 Avg Daily",
                        value=f"₹{avg_daily_expense:,.2f}"
                    )
                
                with col5:
                    st.metric(
                        label="🏷️ Categories",
                        value=f"{expense_df['Category'].nunique()}"
                    )
                
                st.markdown("---")
                
                # Create two columns for visualizations
                col1, col2 = st.columns(2)
                
                with col1:
                    # Pie chart - Expenses by Category
                    st.markdown("### 🥧 Expenses by Category")
                    category_totals = expense_df.groupby('Category')['Amount'].sum().reset_index()
                    category_totals = category_totals.sort_values('Amount', ascending=False)
                    
                    fig_pie = px.pie(
                        category_totals,
                        values='Amount',
                        names='Category',
                        hole=0.4,
                        color_discrete_sequence=px.colors.sequential.RdBu
                    )
                    fig_pie.update_traces(
                        textposition='inside',
                        textinfo='percent+label',
                        hovertemplate='<b>%{label}</b><br>Amount: ₹%{value:,.2f}<br>Percentage: %{percent}<extra></extra>'
                    )
                    fig_pie.update_layout(
                        showlegend=True,
                        height=400,
                        margin=dict(t=20, b=20, l=20, r=20)
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)
                
                with col2:
                    # Bar chart - Top Categories
                    st.markdown("### 📊 Top Expense Categories")
                    top_categories = category_totals.head(10)
                    
                    fig_bar = px.bar(
                        top_categories,
                        x='Amount',
                        y='Category',
                        orientation='h',
                        color='Amount',
                        color_continuous_scale='Viridis',
                        text='Amount'
                    )
                    fig_bar.update_traces(
                        texttemplate='₹%{text:,.0f}',
                        textposition='outside',
                        hovertemplate='<b>%{y}</b><br>Amount: ₹%{x:,.2f}<extra></extra>'
                    )
                    fig_bar.update_layout(
                        showlegend=False,
                        height=400,
                        yaxis={'categoryorder': 'total ascending'},
                        margin=dict(t=20, b=20, l=20, r=20),
                        xaxis_title="Amount (₹)",
                        yaxis_title="Category"
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)
                
                st.markdown("---")
                
                # Account-based analysis (only if not already filtered)
                if 'From' in df.columns and selected_account == 'All Accounts':
                    st.markdown("### 💳 Expenses by Account")
                    
                    # Group by account from the original expense dataframe (before account filter)
                    original_expense_df = df[df['Type'].str.strip() == 'Expense'].copy()
                    original_expense_df['Amount'] = pd.to_numeric(original_expense_df[amount_col], errors='coerce')
                    original_expense_df = original_expense_df.dropna(subset=['Amount'])
                    
                    account_totals = original_expense_df.groupby('From')['Amount'].sum().reset_index()
                    account_totals = account_totals.sort_values('Amount', ascending=False)
                    account_totals.columns = ['Account', 'Amount']
                    
                    # Bar chart for accounts
                    fig_account_bar = px.bar(
                        account_totals,
                        x='Amount',
                        y='Account',
                        orientation='h',
                        color='Amount',
                        color_continuous_scale='Teal',
                        text='Amount'
                    )
                    fig_account_bar.update_traces(
                        texttemplate='₹%{text:,.0f}',
                        textposition='outside',
                        hovertemplate='<b>%{y}</b><br>Amount: ₹%{x:,.2f}<extra></extra>'
                    )
                    fig_account_bar.update_layout(
                        showlegend=False,
                        height=400,
                        yaxis={'categoryorder': 'total ascending'},
                        margin=dict(t=20, b=20, l=20, r=20),
                        xaxis_title="Amount (₹)",
                        yaxis_title="Account"
                    )
                    st.plotly_chart(fig_account_bar, use_container_width=True)
                
                
                # Time series if Date column exists
                if 'Date' in expense_df.columns and expense_df['Date'].notna().any():
                    st.markdown("---")
                    st.markdown("### 📅 Expenses Over Time")
                    
                    # Group by date
                    daily_expenses = expense_df.groupby(expense_df['Date'].dt.date)['Amount'].sum().reset_index()
                    daily_expenses.columns = ['Date', 'Amount']
                    
                    fig_line = px.line(
                        daily_expenses,
                        x='Date',
                        y='Amount',
                        markers=True,
                        line_shape='spline'
                    )
                    fig_line.update_traces(
                        line_color='#667eea',
                        line_width=3,
                        marker=dict(size=8, color='#764ba2'),
                        hovertemplate='<b>Date: %{x}</b><br>Amount: ₹%{y:,.2f}<extra></extra>'
                    )
                    fig_line.update_layout(
                        height=400,
                        margin=dict(t=20, b=20, l=20, r=20),
                        xaxis_title="Date",
                        yaxis_title="Amount (₹)",
                        hovermode='x unified'
                    )
                    st.plotly_chart(fig_line, use_container_width=True)
                
                # Detailed data table
                st.markdown("---")
                st.markdown("### 📝 Detailed Expense Data")
                
                # Prepare display dataframe
                display_columns = ['Date', 'Category', 'Amount']
                if 'From' in expense_df.columns:
                    display_columns.insert(1, 'From')
                
                display_df = expense_df[display_columns].copy()
                display_df = display_df.sort_values('Amount', ascending=False)
                
                # Format amount column
                if 'Amount' in display_df.columns:
                    display_df['Amount'] = display_df['Amount'].apply(lambda x: f"₹{x:,.2f}")
                
                st.dataframe(
                    display_df,
                    use_container_width=True,
                    height=400
                )
                
                # Download processed data
                st.markdown("---")
                csv = expense_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Processed Data (CSV)",
                    data=csv,
                    file_name="expense_data.csv",
                    mime="text/csv"
                )
            
    except Exception as e:
        st.error(f"❌ Error processing file: {str(e)}")
        st.info("Please make sure your Excel file has the correct format with columns: Date, Type, From, To, From Amount")
else:
    # Instructions when no file is uploaded
    st.info("""
    👆 Please upload an Excel or CSV file to get started!
    
    **Expected columns:**
    - Date
    - Type (must contain "Expense" values)
    - From
    - To (will be used as Category)
    - From Amount (will be used as Amount)
    - From Currency
    - To Amount
    - To Currency
    - Comment
    """)
